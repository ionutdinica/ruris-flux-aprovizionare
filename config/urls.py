"""Rutele principale: fiecare modul își declară propriile adrese în `urls.py`,
iar aici doar le „montăm” sub un prefix."""

from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Aprovizionare RURIS – Administrare"
admin.site.site_title = "Aprovizionare RURIS"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("cont/", include("apps.accounts.urls")),
    path("jurnal/", include("apps.audit.urls")),
    path("nomenclatoare/", include("apps.catalog.urls")),
    path("cursuri-bnr/", include("apps.currency.urls")),
    path("comenzi/", include("apps.purchasing.urls")),
    path("facturi/", include("apps.invoicing.urls")),
    path("", include("apps.warehouse.urls")),  # receptii/, discrepante/, stoc/
    path("", include("apps.dashboard.urls")),
]
