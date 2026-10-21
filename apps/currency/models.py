from django.conf import settings
from django.db import models

from apps.core.models import AppendOnlyModel


class ExchangeRate(AppendOnlyModel):
    """Un curs de referință publicat de BNR: câți lei valorează `multiplier` unități de monedă.

    Cursurile publicate sunt fapte: se adaugă, dar nu se mai modifică și nu se șterg.
    Facturile își copiază cursul folosit, deci nici o eventuală corectură ulterioară
    nu ar schimba o factură deja înregistrată.
    """

    date = models.DateField("data")
    currency = models.CharField("moneda", max_length=3)
    rate = models.DecimalField("curs (lei)", max_digits=12, decimal_places=4)
    # BNR publică unele monede la 100 de unități (ex. 100 HUF = 1,4608 lei).
    multiplier = models.PositiveIntegerField("multiplicator", default=1)

    class Meta:
        verbose_name = "curs BNR"
        verbose_name_plural = "cursuri BNR"
        ordering = ["-date", "currency"]
        constraints = [
            # Ordinea câmpurilor contează: indexul servește și căutarea
            # „ultimul curs EUR cu data ≤ X”.
            models.UniqueConstraint(fields=["currency", "date"], name="unique_rate_per_day"),
            models.CheckConstraint(condition=models.Q(rate__gt=0), name="rate_positive"),
            models.CheckConstraint(
                condition=models.Q(multiplier__gt=0), name="rate_multiplier_positive"
            ),
        ]

    def __str__(self):
        return f"{self.currency} {self.rate} ({self.date:%d.%m.%Y})"


class RateSync(AppendOnlyModel):
    """O interogare a BNR: când, ce fișier, cu ce rezultat.

    Pe lângă diagnostic („de când nu mai răspunde BNR?”), răspunde la o întrebare
    pe care cursurile singure nu o pot lămuri: dacă pentru o zi nu avem curs, BNR
    nu l-a publicat ÎNCĂ sau nu îl publică deloc (sărbătoare)? Vezi
    services.is_covered().
    """

    started_at = models.DateTimeField("pornită la", db_index=True)
    url = models.URLField("fișier", max_length=255)
    success = models.BooleanField("reușită")
    rates_created = models.PositiveIntegerField("cursuri noi", default=0)
    latest_date = models.DateField("cel mai recent curs din fișier", null=True, blank=True)
    error = models.TextField("eroare", blank=True)
    # Gol = job-ul automat; altfel, cine a apăsat „Actualizează acum”.
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="pornită de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "actualizare curs BNR"
        verbose_name_plural = "actualizări curs BNR"
        ordering = ["-started_at", "-id"]

    def __str__(self):
        result = "reușită" if self.success else "eșuată"
        return f"Actualizare {result} la {self.started_at:%d.%m.%Y %H:%M}"
