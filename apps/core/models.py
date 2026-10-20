from decimal import Decimal

from django.db import models, transaction

from .text import fold


class ImmutableRecordError(Exception):
    """Încercare de a modifica sau șterge o înregistrare dintr-un registru append-only
    (jurnalul de audit, registrul de stoc)."""


class AppendOnlyQuerySet(models.QuerySet):
    """Blochează și modificările / ștergerile în masă (`.update()`, `.delete()`)."""

    def update(self, **kwargs):
        raise ImmutableRecordError("Înregistrările din acest registru nu pot fi modificate.")

    def delete(self):
        raise ImmutableRecordError("Înregistrările din acest registru nu pot fi șterse.")


class AppendOnlyModel(models.Model):
    """Bază pentru registre: o înregistrare se adaugă, dar nu se mai modifică și nu se
    șterge. Corecturile se fac prin înregistrări noi, vizibile (ex. o ajustare de stoc)."""

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError("Înregistrările din acest registru nu pot fi modificate.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Înregistrările din acest registru nu pot fi șterse.")


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


class VatRate(models.TextChoices):
    """Cotele de TVA din România în vigoare din 1 august 2025 (I-20)."""

    STANDARD = "21.00", "21% (standard)"
    REDUCED = "11.00", "11% (redusă)"
    ZERO = "0.00", "0% (scutit / taxare inversă)"


# Aceleași cote, ca valori Decimal – pentru câmpurile DecimalField(choices=...).
VAT_RATE_CHOICES = [(Decimal(value), label) for value, label in VatRate.choices]
DEFAULT_VAT_RATE = Decimal(VatRate.STANDARD)


class DocumentSequence(models.Model):
    """Contorul numerelor de document, pe tip și an: CMD-2026-0001, CMD-2026-0002...

    Numerele sunt consecutive, fără goluri (documentele nu se șterg). Folosire:
    `DocumentSequence.next_number("CMD", data)` – vezi și docs/05-reguli-business.md §6.
    """

    prefix = models.CharField(max_length=10)
    year = models.PositiveIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["prefix", "year"], name="unique_sequence_per_year")
        ]

    def __str__(self):
        return f"{self.prefix}-{self.year}: {self.last_value}"

    @classmethod
    def next_number(cls, prefix, date):
        with transaction.atomic():
            cls.objects.get_or_create(prefix=prefix, year=date.year)
            # select_for_update blochează rândul până la finalul tranzacției: două
            # documente create în același timp nu pot primi același număr.
            sequence = cls.objects.select_for_update().get(prefix=prefix, year=date.year)
            sequence.last_value += 1
            sequence.save(update_fields=["last_value"])
        return f"{prefix}-{date.year}-{sequence.last_value:04d}"
