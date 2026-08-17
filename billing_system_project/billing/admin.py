from django.contrib import admin

from billing.models import BalanceDenomination, Denomination, Product, Purchase, PurchaseItem


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("product_id", "name", "available_stock", "unit_price", "tax_percentage")
    search_fields = ("product_id", "name")


@admin.register(Denomination)
class DenominationAdmin(admin.ModelAdmin):
    list_display = ("value",)


class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 0
    readonly_fields = [f.name for f in PurchaseItem._meta.fields if f.name != "id"]
    can_delete = False


class BalanceDenominationInline(admin.TabularInline):
    model = BalanceDenomination
    extra = 0
    readonly_fields = ("denomination_value", "count")
    can_delete = False


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ("id", "customer_email", "created_at", "rounded_net_price", "email_sent")
    search_fields = ("customer_email",)
    list_filter = ("email_sent",)
    inlines = [PurchaseItemInline, BalanceDenominationInline]
