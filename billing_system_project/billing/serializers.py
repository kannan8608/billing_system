from decimal import Decimal

from rest_framework import serializers

from billing.models import BalanceDenomination, Denomination, Product, Purchase, PurchaseItem


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "id",
            "product_id",
            "name",
            "available_stock",
            "unit_price",
            "tax_percentage",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class DenominationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Denomination
        fields = ["id", "value"]


# ---------------------------------------------------------------------------
# Bill generation (Page 1 submit)
# ---------------------------------------------------------------------------

class BillItemInputSerializer(serializers.Serializer):
    """One dynamically-added row from the 'Bill section' on Page 1."""

    product_id = serializers.CharField()
    quantity = serializers.IntegerField(min_value=1)


class DenominationCountInputSerializer(serializers.Serializer):
    """One row from the 'Denominations' section on Page 1 (till counts)."""

    value = serializers.IntegerField(min_value=1)
    count = serializers.IntegerField(min_value=0)


class GenerateBillSerializer(serializers.Serializer):
    """Validates the full Page 1 form submission."""

    customer_email = serializers.EmailField()
    items = BillItemInputSerializer(many=True)
    denominations = DenominationCountInputSerializer(many=True, required=False, default=list)
    cash_paid = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0"))

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("At least one product line is required.")
        seen = set()
        for row in items:
            if row["product_id"] in seen:
                raise serializers.ValidationError(
                    f"Product '{row['product_id']}' was added more than once; "
                    "combine into a single quantity instead."
                )
            seen.add(row["product_id"])
        return items


# ---------------------------------------------------------------------------
# Bill / purchase read serializers (Page 2 + history)
# ---------------------------------------------------------------------------

class PurchaseItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseItem
        fields = [
            "product_id_snapshot",
            "product_name_snapshot",
            "unit_price_snapshot",
            "quantity",
            "purchase_price",
            "tax_percentage_snapshot",
            "tax_payable",
            "total_price",
        ]


class BalanceDenominationSerializer(serializers.ModelSerializer):
    class Meta:
        model = BalanceDenomination
        fields = ["denomination_value", "count"]


class PurchaseListSerializer(serializers.ModelSerializer):
    """Lightweight representation used for the purchase-history list."""

    class Meta:
        model = Purchase
        fields = ["id", "customer_email", "created_at", "net_price", "rounded_net_price"]


class PurchaseDetailSerializer(serializers.ModelSerializer):
    """Full representation used for Page 2 / purchase detail."""

    items = PurchaseItemSerializer(many=True, read_only=True)
    balance_denominations = BalanceDenominationSerializer(many=True, read_only=True)

    class Meta:
        model = Purchase
        fields = [
            "id",
            "customer_email",
            "created_at",
            "items",
            "total_price_without_tax",
            "total_tax_payable",
            "net_price",
            "rounded_net_price",
            "cash_paid",
            "balance_amount",
            "balance_denominations",
            "email_sent",
        ]
