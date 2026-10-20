from django.contrib import admin

from .models import Discrepancy, GoodsReceipt, GoodsReceiptLine, StockMovement


class ReadOnlyAdmin(admin.ModelAdmin):
    """Doar pentru consultare și suport: documentele de depozit se gestionează din
    aplicație, unde se aplică regulile (services.py)."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class GoodsReceiptLineInline(admin.TabularInline):
    model = GoodsReceiptLine
    extra = 0
    can_delete = False
    readonly_fields = (
        "product",
        "order_line",
        "quantity_received",
        "quantity_accepted",
        "quantity_quarantined",
        "notes",
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(GoodsReceipt)
class GoodsReceiptAdmin(ReadOnlyAdmin):
    list_display = ("__str__", "supplier", "purchase_order", "receipt_date", "status")
    list_filter = ("status",)
    search_fields = ("number", "supplier__name", "purchase_order__number")
    inlines = [GoodsReceiptLineInline]


@admin.register(Discrepancy)
class DiscrepancyAdmin(ReadOnlyAdmin):
    list_display = ("__str__", "type", "quantity", "status", "resolution", "created_at")
    list_filter = ("status", "type", "resolution")


@admin.register(StockMovement)
class StockMovementAdmin(ReadOnlyAdmin):
    list_display = ("date", "product", "type", "quantity", "order_line", "reason", "created_by")
    list_filter = ("type",)
    search_fields = ("product__code", "product__name", "reason")
