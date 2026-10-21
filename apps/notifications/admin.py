from django.contrib import admin

from .models import NotificationLog


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    """Doar consultare: jurnalul notificărilor nu se modifică."""

    list_display = ("sent_at", "recipient", "email", "kind", "status", "subject")
    list_filter = ("status", "kind")
    search_fields = ("email", "subject", "recipient__username")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
