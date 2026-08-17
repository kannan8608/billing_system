from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from billing.models import Product, Purchase
from billing.utils import compute_change_denominations, round_down_to_whole

# The bill-generation endpoint fires off a real background thread to send
# the invoice email (see billing/utils.py:send_invoice_email_async). That
# thread outlives a single test's transaction, so it races against
# Django's per-test DB teardown (especially with the in-memory sqlite test
# DB) and can log spurious "database is locked" noise. We patch it out in
# API tests below, the same way you would mock any other fire-and-forget
# side effect (e.g. a Celery task) rather than let it run for real.


class RoundDownToWholeTests(TestCase):
    def test_rounds_down_not_to_nearest(self):
        self.assertEqual(round_down_to_whole(Decimal("2357.60")), Decimal("2357"))
        self.assertEqual(round_down_to_whole(Decimal("2357.01")), Decimal("2357"))
        self.assertEqual(round_down_to_whole(Decimal("2357.00")), Decimal("2357"))


class ComputeChangeDenominationsTests(TestCase):
    def test_greedy_breakdown_matches_wireframe_example(self):
        # Wireframe example: balance 643.00 -> {500: 1, 50: 2, 20: 2, 2: 1, 1: 1}
        available = {500: 5, 50: 5, 20: 5, 10: 5, 5: 5, 2: 5, 1: 5}
        result = compute_change_denominations(Decimal("643"), available)
        self.assertEqual(result, {500: 1, 50: 2, 20: 2, 2: 1, 1: 1})

    def test_respects_limited_availability(self):
        # Only one 50 available -> falls back to smaller denominations.
        available = {50: 1, 20: 10, 10: 10, 5: 10, 2: 10, 1: 10}
        result = compute_change_denominations(Decimal("100"), available)
        total = sum(value * count for value, count in result.items())
        self.assertEqual(total, 100)
        self.assertLessEqual(result.get(50, 0), 1)

    def test_raises_when_exact_change_impossible(self):
        with self.assertRaises(ValueError):
            compute_change_denominations(Decimal("3"), {50: 5})

    def test_zero_balance_returns_empty(self):
        self.assertEqual(compute_change_denominations(Decimal("0"), {50: 5}), {})


@mock.patch("billing.views.send_invoice_email_async")
class GenerateBillAPITests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            product_id="SKU-TEST",
            name="Test Widget",
            available_stock=10,
            unit_price=Decimal("100.00"),
            tax_percentage=Decimal("18.00"),
        )
        self.url = reverse("generate-bill")
        self.denominations = [
            {"value": 500, "count": 5},
            {"value": 50, "count": 10},
            {"value": 20, "count": 10},
            {"value": 10, "count": 10},
            {"value": 5, "count": 10},
            {"value": 2, "count": 10},
            {"value": 1, "count": 10},
        ]

    def test_generates_bill_with_correct_totals_and_change(self, mock_send):
        payload = {
            "customer_email": "customer@example.com",
            "items": [{"product_id": "SKU-TEST", "quantity": 2}],
            "denominations": self.denominations,
            "cash_paid": "300.00",
        }
        response = self.client.post(self.url, payload, content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()

        # 2 * 100 = 200 without tax; 18% tax = 36; net = 236; rounded = 236; balance = 64.
        self.assertEqual(data["total_price_without_tax"], "200.00")
        self.assertEqual(data["total_tax_payable"], "36.00")
        self.assertEqual(data["net_price"], "236.00")
        self.assertEqual(data["rounded_net_price"], "236.00")
        self.assertEqual(data["balance_amount"], "64.00")

        self.product.refresh_from_db()
        self.assertEqual(self.product.available_stock, 8)

        purchase = Purchase.objects.get(pk=data["id"])
        self.assertEqual(purchase.customer_email, "customer@example.com")

    def test_rejects_insufficient_stock(self, mock_send):
        payload = {
            "customer_email": "customer@example.com",
            "items": [{"product_id": "SKU-TEST", "quantity": 999}],
            "denominations": self.denominations,
            "cash_paid": "999999",
        }
        response = self.client.post(self.url, payload, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Insufficient stock", response.json()["detail"])

    def test_rejects_insufficient_cash(self, mock_send):
        payload = {
            "customer_email": "customer@example.com",
            "items": [{"product_id": "SKU-TEST", "quantity": 1}],
            "denominations": self.denominations,
            "cash_paid": "1.00",
        }
        response = self.client.post(self.url, payload, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("less than the payable amount", response.json()["detail"])

    def test_unknown_product_id_rejected(self, mock_send):
        payload = {
            "customer_email": "customer@example.com",
            "items": [{"product_id": "DOES-NOT-EXIST", "quantity": 1}],
            "denominations": self.denominations,
            "cash_paid": "100",
        }
        response = self.client.post(self.url, payload, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown product_id", response.json()["detail"])


@mock.patch("billing.views.send_invoice_email_async")
class PurchaseHistoryAPITests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            product_id="SKU-HIST",
            name="History Widget",
            available_stock=10,
            unit_price=Decimal("50.00"),
            tax_percentage=Decimal("0.00"),
        )

    def _generate_bill(self, email):
        payload = {
            "customer_email": email,
            "items": [{"product_id": "SKU-HIST", "quantity": 1}],
            "denominations": [{"value": 50, "count": 5}],
            "cash_paid": "50.00",
        }
        return self.client.post(
            reverse("generate-bill"), payload, content_type="application/json"
        )

    def test_list_filters_by_customer_email(self, mock_send):
        self._generate_bill("alice@example.com")
        self._generate_bill("bob@example.com")

        response = self.client.get(
            reverse("purchase-list"), {"customer_email": "alice@example.com"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["customer_email"], "alice@example.com")

    def test_detail_returns_items(self, mock_send):
        created = self._generate_bill("carol@example.com").json()
        response = self.client.get(reverse("purchase-detail", args=[created["id"]]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 1)
