from django.contrib import admin

from .models import Invoice, InvoiceLine


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0
    can_delete = False
    readonly_fields = ("order_line", "quantity", "unit_price", "vat_rate")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    """Doar consultare și suport: facturile se gestionează din aplicație, unde se aplică
    regulile de potrivire și aprobare (services.py)."""

    list_display = ("number", "supplier", "supplier_invoice_number", "invoice_date", "status")
    list_filter = ("status", "currency")
    search_fields = ("number", "supplier_invoice_number", "supplier__name")
    inlines = [InvoiceLineInline]

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
