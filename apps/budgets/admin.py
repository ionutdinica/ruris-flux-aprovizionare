from django.contrib import admin

from .models import SupplierBudget


@admin.register(SupplierBudget)
class SupplierBudgetAdmin(admin.ModelAdmin):
    list_display = ("supplier", "year", "amount", "currency")
    list_filter = ("year", "currency")
    search_fields = ("supplier__name",)
