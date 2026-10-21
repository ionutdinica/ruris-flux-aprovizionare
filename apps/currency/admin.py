from django.contrib import admin

from .models import ExchangeRate, RateSync


class ReadOnlyAdmin(admin.ModelAdmin):
    """Doar consultare: cursurile vin exclusiv de la BNR, prin services.sync_rates()."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ExchangeRate)
class ExchangeRateAdmin(ReadOnlyAdmin):
    list_display = ("date", "currency", "rate", "multiplier")
    list_filter = ("currency",)
    date_hierarchy = "date"


@admin.register(RateSync)
class RateSyncAdmin(ReadOnlyAdmin):
    list_display = ("started_at", "success", "rates_created", "latest_date", "url", "triggered_by")
    list_filter = ("success",)
