from django.apps import AppConfig


class InvoicingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.invoicing"
    verbose_name = "Facturi"

    def ready(self):
        from . import receivers  # noqa: F401  (înregistrează reacțiile la semnale)
