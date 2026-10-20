from django.db import models

from .text import fold


class TimeStampedModel(models.Model):
    """Bază pentru modelele aplicației: data creării și a ultimei modificări.

    Cine a creat / modificat și ce anume se află în jurnalul de audit.
    „abstract” = nu creează un tabel propriu; câmpurile se copiază în fiecare model.
    """

    created_at = models.DateTimeField("creat la", auto_now_add=True)
    updated_at = models.DateTimeField("modificat la", auto_now=True)

    class Meta:
        abstract = True


class SearchableModel(models.Model):
    """Bază pentru modelele cu căutare tolerantă la diacritice și majuscule.

    La fiecare salvare, câmpurile din SEARCH_FIELDS sunt copiate în `search_text`
    fără diacritice și cu litere mici. Căutarea „otel” găsește astfel „Oțelăria”,
    identic pe SQLite și PostgreSQL. (Notă: `.update()` în masă ocolește save().)
    """

    SEARCH_FIELDS = ()

    search_text = models.TextField(editable=False, blank=True, default="")

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.search_text = self.build_search_text()
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "search_text"}
        super().save(*args, **kwargs)

    def build_search_text(self):
        return fold(" ".join(str(getattr(self, name) or "") for name in self.SEARCH_FIELDS))


class Currency(models.TextChoices):
    """Monedele acceptate (cerința 3: facturile vin în RON sau EUR)."""

    RON = "RON", "RON"
    EUR = "EUR", "EUR"
