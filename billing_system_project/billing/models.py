"""
Models for the Billing System.

Design notes / assumptions (see README for the full list):
- Money fields are stored as Decimal, not float, to avoid floating point
  rounding errors in financial calculations. The task description says
  "float", but Decimal is the production-grade choice for currency and is
  used consistently across the model, the calculation logic, and the API.
- Product.product_id is the human-facing identifier used on the billing
  form (Page 1). It is separate from Django's auto `id` primary key so
  that product codes can be short, meaningful strings (e.g. "SKU-1001").
- A Purchase (the generated bill) stores a *snapshot* of product name,
  unit price and tax percentage on each PurchaseItem line at the time of
  sale. This is standard invoicing practice: if a product's price changes
  later, historical invoices must not change retroactively.
- Denomination counts (500, 50, 20, ... available in the shop / till) are
  supplied fresh with every bill-generation request rather than being
  tracked as a persistent running stock. This matches the wireframe,
  where the cashier enters the current till counts on Page 1 for that
  transaction. This avoids concurrency issues around a shared mutable
  "cash drawer" model and keeps the responsibility of counting the till
  with the cashier, which is how real POS tills are balanced. The
  resulting change breakdown for a bill is still persisted (on
  BalanceDenomination) so that Page 2 / purchase history can show what
  was actually handed back to the customer.
"""
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Product(models.Model):
    """A sellable product / SKU."""

    product_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Human-facing product code entered on the billing form, e.g. SKU-1001.",
    )
    name = models.CharField(max_length=255)
    available_stock = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Price of a single unit, before tax.",
    )
    tax_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Tax percentage applied to this product, e.g. 18.00 for 18%.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.product_id} - {self.name}"


class Denomination(models.Model):
    """
    Reference list of currency denominations the shop deals in
    (500, 50, 20, 10, 5, 2, 1 as shown in the wireframe).

    This is a small admin-managed lookup table so the set of valid
    denominations is not hard-coded in the frontend/back end. It does NOT
    track live stock counts -- see the module docstring above.
    """

    value = models.PositiveIntegerField(unique=True)

    class Meta:
        ordering = ["-value"]

    def __str__(self):
        return str(self.value)


class Purchase(models.Model):
    """
    A single generated bill/invoice for a customer, corresponding to
    "Page 2" in the wireframe.
    """

    customer_email = models.EmailField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    total_price_without_tax = models.DecimalField(max_digits=14, decimal_places=2)
    total_tax_payable = models.DecimalField(max_digits=14, decimal_places=2)
    net_price = models.DecimalField(
        max_digits=14, decimal_places=2, help_text="total_price_without_tax + total_tax_payable"
    )
    rounded_net_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="net_price rounded DOWN to the nearest whole currency unit.",
    )
    cash_paid = models.DecimalField(max_digits=14, decimal_places=2)
    balance_amount = models.DecimalField(
        max_digits=14, decimal_places=2, help_text="cash_paid - rounded_net_price"
    )

    email_sent = models.BooleanField(default=False)
    email_error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Purchase #{self.pk} ({self.customer_email})"


class PurchaseItem(models.Model):
    """One product line within a Purchase. Prices are snapshotted at sale time."""

    purchase = models.ForeignKey(Purchase, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(
        Product, related_name="purchase_items", on_delete=models.SET_NULL, null=True
    )

    # Snapshots -- deliberately duplicated from Product so historical bills
    # remain accurate even if the product is edited or deleted later.
    product_id_snapshot = models.CharField(max_length=64)
    product_name_snapshot = models.CharField(max_length=255)
    unit_price_snapshot = models.DecimalField(max_digits=12, decimal_places=2)
    tax_percentage_snapshot = models.DecimalField(max_digits=5, decimal_places=2)

    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    purchase_price = models.DecimalField(
        max_digits=14, decimal_places=2, help_text="unit_price_snapshot * quantity"
    )
    tax_payable = models.DecimalField(
        max_digits=14, decimal_places=2, help_text="purchase_price * tax_percentage_snapshot / 100"
    )
    total_price = models.DecimalField(
        max_digits=14, decimal_places=2, help_text="purchase_price + tax_payable"
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.product_id_snapshot} x{self.quantity} (Purchase #{self.purchase_id})"


class BalanceDenomination(models.Model):
    """
    The breakdown of a Purchase's change (balance_amount) into
    denomination counts, e.g. {500: 1, 50: 2, 20: 2, 2: 1, 1: 1}.
    """

    purchase = models.ForeignKey(
        Purchase, related_name="balance_denominations", on_delete=models.CASCADE
    )
    denomination_value = models.PositiveIntegerField()
    count = models.PositiveIntegerField()

    class Meta:
        ordering = ["-denomination_value"]

    def __str__(self):
        return f"{self.denomination_value} x{self.count} (Purchase #{self.purchase_id})"
