from django.conf import settings
from django.db import models

from apps.core.models import AppendOnlyModel


class NotificationLog(AppendOnlyModel):
    """Un rezumat trimis (sau încercat): cui, când, ce conținea, cu ce rezultat.

    Servește la trei lucruri: nu trimitem de două ori în aceeași zi; marcăm „NOU” ce
    nu era în rezumatul anterior (`items`); arătăm în aplicație ce s-a trimis
    (pagina „Notificări trimise”), util și când cineva spune „n-am primit nimic”.
    """

    class Status(models.TextChoices):
        SENT = "SENT", "Trimis"
        FAILED = "FAILED", "Eșuat"

    class Kind(models.TextChoices):
        DAILY = "DAILY", "Rezumat zilnic"
        MANUAL = "MANUAL", "Trimis manual („Trimite acum”)"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="destinatar",
        on_delete=models.PROTECT,
        related_name="notifications",
    )
    email = models.EmailField("adresa folosită")  # adresa de la momentul trimiterii
    sent_at = models.DateTimeField("trimis la", auto_now_add=True, db_index=True)
    kind = models.CharField("tip", max_length=10, choices=Kind.choices, default=Kind.DAILY)
    subject = models.CharField("subiect", max_length=200)
    body_text = models.TextField("conținut")
    # Cheile problemelor incluse (ex. "ORDER_LATE:12"): pentru marcajul „NOU” data viitoare.
    items = models.JSONField("probleme incluse", default=list)
    status = models.CharField("rezultat", max_length=10, choices=Status.choices)
    error = models.TextField("eroare", blank=True)
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="trimis de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "notificare trimisă"
        verbose_name_plural = "notificări trimise"
        ordering = ["-sent_at", "-id"]
        indexes = [models.Index(fields=["recipient", "-sent_at"])]

    def __str__(self):
        return f"{self.subject} → {self.email} ({self.get_status_display().lower()})"


class DailyDigestRun(models.Model):
    """„Rezumatul zilei X a fost făcut”, cu bilanțul lui.

    Job-ul rulează la fiecare 10 minute; fără această evidență, cine nu avea nimic de
    rezolvat la 08:00 ar primi un „rezumat zilnic” la prima problemă apărută în cursul
    zilei. După rularea zilei, job-ul doar reîncearcă emailurile eșuate.
    """

    date = models.DateField("ziua", unique=True)
    started_at = models.DateTimeField("pornit la", auto_now_add=True)
    sent = models.PositiveIntegerField("trimise", default=0)
    failed = models.PositiveIntegerField("eșuate", default=0)
    nothing_to_report = models.PositiveIntegerField("fără probleme", default=0)

    class Meta:
        verbose_name = "rulare a rezumatului zilnic"
        verbose_name_plural = "rulări ale rezumatului zilnic"
        ordering = ["-date"]

    def __str__(self):
        return f"Rezumatul din {self.date:%d.%m.%Y}: {self.sent} trimise, {self.failed} eșuate"
