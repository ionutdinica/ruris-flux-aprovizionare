from django.contrib import admin

from .models import Product, Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "tax_id", "country", "email", "default_currency", "is_active")
    list_filter = ("is_active", "country", "default_currency")
    search_fields = ("name", "tax_id", "email")

    def has_delete_permission(self, request, obj=None):
        return False  # se dezactivează, nu se șterg (sunt referiți de documente)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "unit", "vat_rate", "is_active")
    list_filter = ("is_active", "unit", "vat_rate")
    search_fields = ("code", "name")

    def has_delete_permission(self, request, obj=None):
        return False
