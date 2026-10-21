"""Facturile furnizorilor (Contabilitate).

O factură are un singur furnizor și o singură monedă; fiecare linie a ei e legată de
o linie de comandă (I-18: o factură poate acoperi mai multe comenzi ale aceluiași
furnizor, o comandă poate fi facturată în mai multe facturi).

Statusurile sunt în docs/03-fluxuri-si-stari.md; ele se schimbă DOAR prin funcțiile
din services.py. Verificarea comandă–recepție–factură e în matching.py.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Supplier
from apps.core.models import (
    DEFAULT_VAT_RATE,
    VAT_RATE_CHOICES,
    Currency,
    DocumentSequence,
    SearchableModel,
    TimeStampedModel,
)
from apps.core.text import fold, format_quantity
from apps.purchasing.models import PurchaseOrderLine, money

ZERO = Decimal("0")
AMOUNT = {"max_digits": 14, "decimal_places": 2}


class Invoice(SearchableModel, TimeStampedModel):
    class Status(models.TextChoices):
        REGISTERED = "REGISTERED", "Înregistrată"
        RATE_PENDING = "RATE_PENDING", "Curs în așteptare"
        MATCHED = "MATCHED", "Potrivită"
        BLOCKED = "BLOCKED", "Blocată"
        APPROVED = "APPROVED", "Aprobată la plată"
        PAID = "PAID", "Plătită"
        REJECTED = "REJECTED", "Respinsă"

    STATUS_COLORS = {
        Status.REGISTERED: "secondary",
        Status.RATE_PENDING: "warning",
        Status.MATCHED: "success",
        Status.BLOCKED: "danger",
        Status.APPROVED: "primary",
        Status.PAID: "dark",
        Status.REJECTED: "light",
    }

    # Ce nu apare în istoricul facturii pentru cine nu vede detaliile plății (Achizițiile).
    AUDIT_RESTRICTED = {
        "invoices.view_payment": {
            "fields": ("paid_at", "payment_reference"),
            "details": ("data plății", "referința"),
        }
    }

    # Facturile care se reverifică automat când se schimbă recepțiile sau comenzile.
    # Cele aprobate și plătite nu: decizia de plată a fost luată și e consemnată.
    RECHECKABLE_STATUSES = (Status.MATCHED, Status.BLOCKED)
    # Facturile care contează la „facturat” pe o linie de comandă (progresul comenzii).
    INVOICED_STATUSES = (
        Status.RATE_PENDING,
        Status.MATCHED,
        Status.BLOCKED,
        Status.APPROVED,
        Status.PAID,
    )

    number = models.CharField("număr intern", max_length=20, unique=True, editable=False)
    supplier = models.ForeignKey(
        Supplier, verbose_name="furnizor", on_delete=models.PROTECT, related_name="invoices"
    )
    supplier_invoice_number = models.CharField("număr factură furnizor", max_length=50)
    invoice_date = models.DateField("data facturii")
    due_date = models.DateField("scadența")
    currency = models.CharField("monedă", max_length=3, choices=Currency.choices)

    # Totalurile de pe documentul fizic, introduse de Contabilitate (I-19). Se compară
    # cu cele calculate din linii: așa se prind greșelile de pe factură sau de tastare.
    declared_net = models.DecimalField(
        "total fără TVA (de pe factură)", **AMOUNT, validators=[MinValueValidator(ZERO)]
    )
    declared_vat = models.DecimalField(
        "TVA (de pe factură)", **AMOUNT, validators=[MinValueValidator(ZERO)]
    )
    declared_total = models.DecimalField(
        "total de plată (de pe factură)", **AMOUNT, validators=[MinValueValidator(ZERO)]
    )

    # Cursul BNR, stabilit la validare și apoi fix (I-24, I-25).
    exchange_rate = models.DecimalField(
        "curs BNR", max_digits=12, decimal_places=4, null=True, blank=True, editable=False
    )
    exchange_rate_date = models.DateField("data cursului", null=True, blank=True, editable=False)
    total_ron = models.DecimalField("total în lei", **AMOUNT, null=True, blank=True, editable=False)

    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.REGISTERED, editable=False
    )
    # Rezultatul ultimei potriviri: lista motivelor de blocare (cod + mesaj).
    match_result = models.JSONField("motive de blocare", default=list, blank=True, editable=False)
    matched_at = models.DateTimeField("verificată la", null=True, blank=True, editable=False)

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="aprobată de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    approved_at = models.DateTimeField("aprobată la", null=True, blank=True, editable=False)
    override_reason = models.TextField("justificarea forțării", blank=True, editable=False)
    paid_at = models.DateField("plătită la", null=True, blank=True, editable=False)
    payment_reference = models.CharField(
        "referința plății", max_length=100, blank=True, editable=False
    )
    rejection_reason = models.TextField("motivul respingerii", blank=True, editable=False)
    notes = models.TextField("observații", blank=True)

    class Meta:
        verbose_name = "factură"
        verbose_name_plural = "facturi"
        ordering = ["-invoice_date", "-number"]
        constraints = [
            # Aceeași factură nu poate fi introdusă de două ori: protecție la dublă
            # plată (I-21). Garantat de baza de date, nu doar de formular.
            models.UniqueConstraint(
                fields=["supplier", "supplier_invoice_number"],
                name="unique_invoice_number_per_supplier",
                violation_error_message=(
                    "Această factură a fost deja înregistrată: există o factură cu același "
                    "număr de la același furnizor."
                ),
            ),
            models.CheckConstraint(
                condition=Q(due_date__gte=models.F("invoice_date")),
                name="invoice_due_after_date",
                violation_error_message="Scadența nu poate fi înaintea datei facturii.",
            ),
        ]

    def __str__(self):
        return self.number or "factură nouă"

    def save(self, *args, **kwargs):
        if not self.number:
            # Numărul intern urmează ordinea înregistrării (registrul de intrări).
            self.number = DocumentSequence.next_number("FAC", timezone.localdate())
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("invoicing:invoice_detail", args=[self.pk])

    def build_search_text(self):
        supplier = self.supplier.name if self.supplier_id else ""
        return fold(f"{self.number} {self.supplier_invoice_number} {supplier} {self.notes}")

    def clean(self):
        errors = {}
        if self.invoice_date and self.invoice_date > timezone.localdate():
            errors["invoice_date"] = "Data facturii nu poate fi în viitor (I-27)."
        if self.invoice_date and self.due_date and self.due_date < self.invoice_date:
            errors["due_date"] = "Scadența nu poate fi înaintea datei facturii."
        if errors:
            raise ValidationError(errors)

    @property
    def status_color(self):
        return self.STATUS_COLORS[self.status]

    @property
    def is_editable(self):
        """Doar o factură înregistrată (nevalidată încă) se poate modifica."""
        return self.status == self.Status.REGISTERED

    @property
    def problems(self):
        """Motivele de blocare de la ultima potrivire (listă de dicționare cod + mesaj)."""
        return self.match_result or []

    # --- Totaluri calculate din linii (comparate cu cele declarate) ---------------------

    @property
    def computed_net(self):
        return sum((line.net_amount for line in self.lines.all()), ZERO)

    @property
    def computed_vat(self):
        return sum((line.vat_amount for line in self.lines.all()), ZERO)

    @property
    def computed_total(self):
        return self.computed_net + self.computed_vat


class InvoiceLine(TimeStampedModel):
    invoice = models.ForeignKey(
        Invoice, verbose_name="factură", on_delete=models.CASCADE, related_name="lines"
    )
    order_line = models.ForeignKey(
        PurchaseOrderLine,
        verbose_name="linie de comandă",
        on_delete=models.PROTECT,
        related_name="invoice_lines",
    )
    quantity = models.DecimalField(
        "cantitate",
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"), "Cantitatea trebuie să fie pozitivă.")],
    )
    unit_price = models.DecimalField(
        "preț unitar",
        max_digits=14,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"), "Prețul trebuie să fie pozitiv.")],
    )
    vat_rate = models.DecimalField(
        "cota TVA (%)",
        max_digits=5,
        decimal_places=2,
        choices=VAT_RATE_CHOICES,
        default=DEFAULT_VAT_RATE,
    )

    class Meta:
        verbose_name = "linie de factură"
        verbose_name_plural = "linii de factură"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="invoice_line_quantity_positive"
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gt=0), name="invoice_line_price_positive"
            ),
        ]

    def __str__(self):
        product = self.order_line.product.code if self.order_line_id else "?"
        return f"{self.invoice} · {product} × {format_quantity(self.quantity)}"

    def get_additional_data(self):
        """Modificările liniilor apar în istoricul facturii (apps/audit/timeline.py)."""
        return {"parent": f"invoicing.invoice:{self.invoice_id}"}

    @property
    def net_amount(self):
        return money(self.quantity * self.unit_price)

    @property
    def vat_amount(self):
        return money(self.net_amount * self.vat_rate / 100)
