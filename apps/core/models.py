from django.db import models


class TimeStampedModel(models.Model):
    """Bază pentru modelele aplicației: data creării și a ultimei modificări.

    Cine a creat / modificat și ce anume se află în jurnalul de audit.
    „abstract” = nu creează un tabel propriu; câmpurile se copiază în fiecare model.
    """

    created_at = models.DateTimeField("creat la", auto_now_add=True)
    updated_at = models.DateTimeField("modificat la", auto_now=True)

    class Meta:
        abstract = True


class Currency(models.TextChoices):
    """Monedele acceptate (cerința 3: facturile vin în RON sau EUR)."""

    RON = "RON", "RON"
    EUR = "EUR", "EUR"
