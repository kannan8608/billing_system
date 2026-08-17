"""
Management command to seed sample Product and Denomination data, so the
app has something to bill against immediately after `migrate`.

Usage:
    python manage.py seed_products
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from billing.models import Denomination, Product

SAMPLE_PRODUCTS = [
    dict(product_id="SKU-1001", name="Wireless Mouse", available_stock=50,
         unit_price=Decimal("699.00"), tax_percentage=Decimal("18.00")),
    dict(product_id="SKU-1002", name="Mechanical Keyboard", available_stock=30,
         unit_price=Decimal("2499.00"), tax_percentage=Decimal("18.00")),
    dict(product_id="SKU-1003", name="USB-C Cable", available_stock=100,
         unit_price=Decimal("199.00"), tax_percentage=Decimal("12.00")),
    dict(product_id="SKU-1004", name="Notebook (A5)", available_stock=200,
         unit_price=Decimal("49.00"), tax_percentage=Decimal("5.00")),
    dict(product_id="SKU-1005", name="Desk Lamp", available_stock=20,
         unit_price=Decimal("899.00"), tax_percentage=Decimal("18.00")),
]

DEFAULT_DENOMINATIONS = [500, 50, 20, 10, 5, 2, 1]


class Command(BaseCommand):
    help = "Seed sample products and denominations."

    def handle(self, *args, **options):
        created_products = 0
        for row in SAMPLE_PRODUCTS:
            _, created = Product.objects.get_or_create(
                product_id=row["product_id"], defaults=row
            )
            created_products += int(created)

        created_denominations = 0
        for value in DEFAULT_DENOMINATIONS:
            _, created = Denomination.objects.get_or_create(value=value)
            created_denominations += int(created)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created_products} new product(s) and "
                f"{created_denominations} new denomination(s)."
            )
        )
