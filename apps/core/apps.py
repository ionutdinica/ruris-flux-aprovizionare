from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Piese comune tuturor modulelor (modele abstracte, validatoare, formulare)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Comun"
