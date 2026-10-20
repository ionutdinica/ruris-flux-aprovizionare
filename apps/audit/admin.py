from django.contrib import admin

from .models import BusinessEvent


@admin.register(BusinessEvent)
class BusinessEventAdmin(admin.ModelAdmin):
    """Doar citire: jurnalul nu se adaugă, nu se modifică și nu se șterge manual."""

    list_display = ("timestamp", "event_type", "actor", "object_repr", "message", "remote_addr")
    list_filter = ("event_type", "timestamp")
    search_fields = ("message", "object_repr", "actor__username")
    date_hierarchy = "timestamp"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
