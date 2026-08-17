from decimal import Decimal

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.models import BalanceDenomination, Product, Purchase, PurchaseItem
from billing.serializers import (
    GenerateBillSerializer,
    ProductSerializer,
    PurchaseDetailSerializer,
    PurchaseListSerializer,
)
from billing.utils import (
    build_invoice_email_body,
    compute_change_denominations,
    round_down_to_whole,
    send_invoice_email_async,
)


class ProductViewSet(viewsets.ModelViewSet):
    """
    Full CRUD for products, e.g.:
      GET/POST   /api/products/
      GET/PUT/PATCH/DELETE /api/products/<pk>/

    Lookup by product_id (not to be confused with the Product's own name).
    """

    queryset = Product.objects.all()
    serializer_class = ProductSerializer


class GenerateBillAPIView(APIView):
    """
    POST /api/purchases/generate-bill/

    Body:
    {
      "customer_email": "person@example.com",
      "items": [{"product_id": "SKU-1", "quantity": 2}, ...],
      "denominations": [{"value": 500, "count": 3}, {"value": 50, "count": 10}, ...],
      "cash_paid": "3000.00"
    }

    This is the "Generate Bill" button on Page 1. It:
      1. Prices every line item against the current Product record.
      2. Computes totals, applies floor-rounding to get the payable amount.
      3. Validates the customer paid enough and works out the change.
      4. Breaks the change down into denominations available in the till
         (the `denominations` the cashier entered on Page 1).
      5. Persists everything atomically and decrements stock.
      6. Kicks off an async email to the customer.
    """

    def post(self, request):
        serializer = GenerateBillSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        product_ids = [row["product_id"] for row in data["items"]]
        products_by_id = {
            p.product_id: p for p in Product.objects.filter(product_id__in=product_ids)
        }

        missing = [pid for pid in product_ids if pid not in products_by_id]
        if missing:
            return Response(
                {"detail": f"Unknown product_id(s): {', '.join(missing)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Stock check before we commit to anything.
        insufficient = []
        for row in data["items"]:
            product = products_by_id[row["product_id"]]
            if product.available_stock < row["quantity"]:
                insufficient.append(
                    f"{product.product_id} (requested {row['quantity']}, "
                    f"available {product.available_stock})"
                )
        if insufficient:
            return Response(
                {"detail": f"Insufficient stock for: {', '.join(insufficient)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        total_without_tax = Decimal("0")
        total_tax = Decimal("0")
        item_rows = []
        for row in data["items"]:
            product = products_by_id[row["product_id"]]
            quantity = row["quantity"]
            purchase_price = (product.unit_price * quantity).quantize(Decimal("0.01"))
            tax_payable = (purchase_price * product.tax_percentage / Decimal("100")).quantize(
                Decimal("0.01")
            )
            line_total = purchase_price + tax_payable

            total_without_tax += purchase_price
            total_tax += tax_payable

            item_rows.append(
                {
                    "product": product,
                    "quantity": quantity,
                    "purchase_price": purchase_price,
                    "tax_payable": tax_payable,
                    "total_price": line_total,
                }
            )

        net_price = total_without_tax + total_tax
        rounded_net_price = round_down_to_whole(net_price)
        cash_paid = data["cash_paid"]

        if cash_paid < rounded_net_price:
            return Response(
                {
                    "detail": (
                        f"Cash paid ({cash_paid:.2f}) is less than the payable amount "
                        f"({rounded_net_price:.2f})."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        balance_amount = round_down_to_whole(cash_paid - rounded_net_price)

        available_denominations = {
            row["value"]: row["count"] for row in data.get("denominations", [])
        }
        try:
            change_breakdown = compute_change_denominations(balance_amount, available_denominations)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            purchase = Purchase.objects.create(
                customer_email=data["customer_email"],
                total_price_without_tax=total_without_tax,
                total_tax_payable=total_tax,
                net_price=net_price,
                rounded_net_price=rounded_net_price,
                cash_paid=cash_paid,
                balance_amount=balance_amount,
            )

            purchase_items = []
            for row in item_rows:
                product = row["product"]
                purchase_items.append(
                    PurchaseItem(
                        purchase=purchase,
                        product=product,
                        product_id_snapshot=product.product_id,
                        product_name_snapshot=product.name,
                        unit_price_snapshot=product.unit_price,
                        tax_percentage_snapshot=product.tax_percentage,
                        quantity=row["quantity"],
                        purchase_price=row["purchase_price"],
                        tax_payable=row["tax_payable"],
                        total_price=row["total_price"],
                    )
                )
                # Decrement stock.
                product.available_stock -= row["quantity"]
            PurchaseItem.objects.bulk_create(purchase_items)
            Product.objects.bulk_update(
                [row["product"] for row in item_rows], ["available_stock"]
            )

            BalanceDenomination.objects.bulk_create(
                [
                    BalanceDenomination(purchase=purchase, denomination_value=value, count=count)
                    for value, count in change_breakdown.items()
                ]
            )

        purchase.refresh_from_db()
        body = build_invoice_email_body(purchase)
        send_invoice_email_async(purchase, plain_text_body=body)

        detail = PurchaseDetailSerializer(purchase).data
        return Response(detail, status=status.HTTP_201_CREATED)


class PurchaseListAPIView(APIView):
    """
    GET /api/purchases/?customer_email=person@example.com

    Lists previous purchases for a customer (the "view previous purchases" feature).
    """

    def get(self, request):
        email = request.query_params.get("customer_email", "").strip()
        if not email:
            return Response(
                {"detail": "Query parameter 'customer_email' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        purchases = Purchase.objects.filter(customer_email__iexact=email)
        return Response(PurchaseListSerializer(purchases, many=True).data)


class PurchaseDetailAPIView(APIView):
    """
    GET /api/purchases/<pk>/

    Full detail for a single purchase -- selecting a purchase from the
    history list shows this (matches Page 2 layout).
    """

    def get(self, request, pk):
        purchase = get_object_or_404(Purchase, pk=pk)
        return Response(PurchaseDetailSerializer(purchase).data)
