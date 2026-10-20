"""Rutele principale: fiecare modul își declară propriile adrese în `urls.py`,
iar aici doar le „montăm” sub un prefix."""

from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Aprovizionare RURIS – Administrare"
admin.site.site_title = "Aprovizionare RURIS"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("cont/", include("apps.accounts.urls")),
    path("", include("apps.dashboard.urls")),
]
