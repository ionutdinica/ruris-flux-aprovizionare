from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "get_full_name", "email", "role", "is_active")
    list_filter = ("role", "is_active")
    fieldsets = UserAdmin.fieldsets + (("Rol în aplicație", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Date obligatorii", {"fields": ("email", "role")}),)

    def has_delete_permission(self, request, obj=None):
        # Utilizatorii nu se șterg, se dezactivează (bifa „Activ”): altfel s-ar
        # pierde legătura cu tot ce au făcut, înregistrat în jurnalul de audit.
        return False
