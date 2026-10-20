from django.contrib import admin

from .models import PurchaseOrder, PurchaseOrderLine


class PurchaseOrderLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 0


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    """Doar pentru consultare și suport; comenzile se gestionează din aplicație,
    unde se aplică regulile de status (services.py)."""

    list_display = ("number", "supplier", "owner", "status", "order_date", "expected_date")
    list_filter = ("status", "currency")
    search_fields = ("number", "supplier__name")
    readonly_fields = ("number", "status", "sent_at", "close_reason")
    inlines = [PurchaseOrderLineInline]

    def has_delete_permission(self, request, obj=None):
        return False
