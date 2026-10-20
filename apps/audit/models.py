"""Evenimente de business pentru jurnalul de audit.

Jurnalul automat (django-auditlog) răspunde la „ce câmp s-a schimbat?”.
Unele acțiuni importante nu sunt simple modificări de câmpuri și au nevoie
de context: cine a intrat în aplicație, cine a forțat o factură la plată și
cu ce justificare etc. Acestea se înregistrează explicit, ca BusinessEvent.

Ambele jurnale sunt „append-only”: o înregistrare, odată scrisă, nu mai poate
fi modificată sau ștearsă din aplicație.
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class ImmutableRecordError(Exception):
    """Încercare de a modifica sau șterge o înregistrare din jurnalul de audit."""


class AppendOnlyQuerySet(models.QuerySet):
    """Blochează și modificările / ștergerile în masă (`.update()`, `.delete()`)."""

    def update(self, **kwargs):
        raise ImmutableRecordError("Jurnalul de audit nu poate fi modificat.")

    def delete(self):
        raise ImmutableRecordError("Jurnalul de audit nu poate fi șters.")


class BusinessEvent(models.Model):
    class Type(models.TextChoices):
        # Catalogul evenimentelor; se completează în fiecare capitol.
        LOGIN = "auth.login", "Autentificare"
        LOGOUT = "auth.logout", "Ieșire din cont"
        LOGIN_FAILED = "auth.login_failed", "Autentificare eșuată"
        ORDER_SENT = "order.sent", "Comandă trimisă"
        ORDER_CANCELLED = "order.cancelled", "Comandă anulată"
        ORDER_CLOSED = "order.closed", "Comandă închisă cu rest"

    timestamp = models.DateTimeField("data și ora", auto_now_add=True, db_index=True)
    # PROTECT: un utilizator cu istoric nu poate fi șters (doar dezactivat),
    # altfel s-ar pierde „cine” din jurnal.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="utilizator",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_events",
    )
    event_type = models.CharField("eveniment", max_length=64, choices=Type.choices, db_index=True)
    message = models.TextField("descriere")

    # Documentul la care se referă evenimentul (comandă, factură...), opțional.
    # O „cheie generică” poate indica spre orice tip de model.
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, null=True, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    target = GenericForeignKey("content_type", "object_id")
    object_repr = models.CharField("document", max_length=255, blank=True)

    data = models.JSONField("detalii", default=dict, blank=True)  # ex. {"justificare": "..."}
    remote_addr = models.GenericIPAddressField("adresă IP", null=True, blank=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        verbose_name = "eveniment"
        verbose_name_plural = "evenimente"
        ordering = ["-timestamp", "-id"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return f"{self.timestamp:%d.%m.%Y %H:%M} · {self.get_event_type_display()}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError("Jurnalul de audit nu poate fi modificat.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Jurnalul de audit nu poate fi șters.")
