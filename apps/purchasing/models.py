"""Comenzile către furnizori (Achiziții).

O comandă are un singur furnizor și o singură monedă (I-05) și una sau mai
multe linii, fiecare cu propria dată estimată de sosire (I-06). Statusurile și
tranzițiile sunt descrise în docs/03-fluxuri-si-stari.md; tranzițiile se fac
DOAR prin funcțiile din services.py, nu prin modificarea directă a statusului.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import (
    BooleanField,
    Case,
    DecimalField,
    Exists,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Round
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Product, Supplier
from apps.core.models import (
    DEFAULT_VAT_RATE,
    VAT_RATE_CHOICES,
    Currency,
    DocumentSequence,
    SearchableModel,
    TimeStampedModel,
)
from apps.core.text import fold, format_quantity

CENT = Decimal("0.01")
ZERO = Decimal("0")


def money(value):
    """Rotunjire la bani (2 zecimale), ca în contabilitate: 0,005 → 0,01."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


class PurchaseOrderQuerySet(models.QuerySet):
    def open(self):
        """Comenzile la care se mai așteaptă marfă."""
        return self.filter(status__in=PurchaseOrder.OPEN_STATUSES)

    def late(self, today=None):
        """Comenzile deschise cu cel puțin o linie întârziată (docs/05 §4, ORDER_LATE)."""
        today = today or timezone.localdate()
        late_lines = PurchaseOrderLine.objects.with_progress().filter(
            expected_date__lt=today, received_qty__lt=F("quantity")
        )
        return self.open().filter(pk__in=late_lines.values("order_id"))

    def with_late_flag(self, today=None):
        """Adaugă `is_late` fiecărei comenzi (evidențiere în liste), calculat în baza de date."""
        today = today or timezone.localdate()
        late_lines = PurchaseOrderLine.objects.with_progress().filter(
            order=OuterRef("pk"), expected_date__lt=today, received_qty__lt=F("quantity")
        )
        return self.annotate(
            is_late=Case(
                When(Q(status__in=PurchaseOrder.OPEN_STATUSES) & Exists(late_lines), then=True),
                default=False,
                output_field=BooleanField(),
            )
        )

    def visible_to(self, user):
        """Ciornele sunt interne Achizițiilor: celelalte echipe văd comenzile
        abia după trimitere, când devin angajament față de furnizor."""
        if user.can("orders.edit"):
            return self
        return self.exclude(status=PurchaseOrder.Status.DRAFT)

    def with_totals(self):
        """Adaugă valoarea fără TVA a fiecărei comenzi (pentru liste), calculată în baza de date."""
        line_net = Round(F("lines__quantity") * F("lines__unit_price"), 2)
        return self.annotate(
            net_total=Coalesce(Sum(line_net), Value(ZERO), output_field=DecimalField())
        )


class PurchaseOrder(SearchableModel, TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Ciornă"
        SENT = "SENT", "Trimisă"
        PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED", "Parțial recepționată"
        RECEIVED = "RECEIVED", "Recepționată"
        CLOSED = "CLOSED", "Închisă"
        CANCELLED = "CANCELLED", "Anulată"

    # Culoarea Bootstrap a fiecărui status, pentru etichete.
    STATUS_COLORS = {
        Status.DRAFT: "secondary",
        Status.SENT: "primary",
        Status.PARTIALLY_RECEIVED: "info",
        Status.RECEIVED: "success",
        Status.CLOSED: "dark",
        Status.CANCELLED: "danger",
    }

    # Comenzi la care se așteaptă marfă (pot fi întârziate).
    OPEN_STATUSES = (Status.SENT, Status.PARTIALLY_RECEIVED)
    # Comenzi care mai acceptă modificări controlate: termene, linii noi, cantități mai
    # mari (I-07). Inclusiv cele recepționate complet: așa se poate regulariza un surplus.
    AMENDABLE_STATUSES = (Status.SENT, Status.PARTIALLY_RECEIVED, Status.RECEIVED)

    number = models.CharField("număr", max_length=20, unique=True, editable=False)
    external_reference = models.CharField(
        "referință externă",
        max_length=50,
        blank=True,
        help_text="Opțional: numărul comenzii din Excel-ul vechi sau de la furnizor.",
    )
    supplier = models.ForeignKey(
        Supplier, verbose_name="furnizor", on_delete=models.PROTECT, related_name="orders"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="responsabil",
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        help_text="Primește notificările despre această comandă.",
    )
    currency = models.CharField("monedă", max_length=3, choices=Currency.choices)
    order_date = models.DateField("data comenzii", default=timezone.localdate)
    expected_date = models.DateField(
        "data estimată de sosire", help_text="Implicită pentru liniile fără o dată proprie."
    )
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.DRAFT, editable=False
    )
    sent_at = models.DateTimeField("trimisă la", null=True, blank=True, editable=False)
    close_reason = models.TextField("motivul închiderii / anulării", blank=True, editable=False)
    notes = models.TextField("observații", blank=True)

    objects = PurchaseOrderQuerySet.as_manager()

    class Meta:
        verbose_name = "comandă"
        verbose_name_plural = "comenzi"
        ordering = ["-order_date", "-number"]
        constraints = [
            # Aceeași referință externă nu poate apărea de două ori la același furnizor
            # (ex. același fișier Excel importat de două ori). Garantat de baza de date.
            models.UniqueConstraint(
                fields=["supplier", "external_reference"],
                condition=~Q(external_reference=""),
                name="unique_external_reference_per_supplier",
                violation_error_message=(
                    "Există deja o comandă cu această referință externă pentru acest furnizor."
                ),
            )
        ]

    def __str__(self):
        return self.number or "comandă nouă"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = DocumentSequence.next_number("CMD", self.order_date)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("purchasing:order_detail", args=[self.pk])

    def build_search_text(self):
        supplier = self.supplier.name if self.supplier_id else ""
        return fold(f"{self.number} {self.external_reference} {supplier} {self.notes}")

    def clean(self):
        errors = {}
        if self.supplier_id and not self.supplier.is_active and self._state.adding:
            errors["supplier"] = "Furnizorul este inactiv și nu mai poate fi ales pe comenzi noi."
        if self.order_date and self.expected_date and self.expected_date < self.order_date:
            errors["expected_date"] = "Data estimată nu poate fi înaintea datei comenzii."
        if errors:
            raise ValidationError(errors)

    @property
    def status_color(self):
        return self.STATUS_COLORS[self.status]

    # --- Ce se poate face în statusul curent --------------------------------------

    @property
    def is_editable(self):
        """Ciornă: se poate modifica orice."""
        return self.status == self.Status.DRAFT

    @property
    def is_amendable(self):
        """După trimitere: doar termene, linii noi, cantități mai mari (I-07)."""
        return self.status in self.AMENDABLE_STATUSES

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    # --- Totaluri -------------------------------------------------------------------

    @property
    def net_amount(self):
        return sum((line.net_amount for line in self.lines.all()), ZERO)

    @property
    def vat_amount(self):
        return sum((line.vat_amount for line in self.lines.all()), ZERO)

    @property
    def gross_amount(self):
        return self.net_amount + self.vat_amount


class PurchaseOrderLineQuerySet(models.QuerySet):
    def with_progress(self):
        """Adaugă cantitățile recepționate și facturate ale fiecărei linii.

        Calculate din documente, nu stocate (docs/02-model-date.md): nu se pot
        desincroniza. Recepționat = suma mișcărilor de stoc ale liniei din registrul
        depozitului (recepții + marfă acceptată din carantină − retururi).
        Facturat: capitolul 7; până atunci zero.
        """
        from apps.warehouse.models import StockMovement  # import aici: evită importul circular

        decimal = DecimalField(max_digits=15, decimal_places=3)
        received = (
            StockMovement.objects.filter(order_line=OuterRef("pk"))
            .order_by()
            .values("order_line")
            .annotate(total=Sum("quantity"))
            .values("total")
        )
        return self.annotate(
            received_qty=Coalesce(
                Subquery(received, output_field=decimal), Value(ZERO), output_field=decimal
            ),
            invoiced_qty=Value(ZERO, output_field=decimal),
        )


class PurchaseOrderLine(TimeStampedModel):
    order = models.ForeignKey(
        PurchaseOrder, verbose_name="comandă", on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(Product, verbose_name="produs", on_delete=models.PROTECT)
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
        validators=[MinValueValidator(ZERO, "Prețul nu poate fi negativ.")],
    )
    vat_rate = models.DecimalField(
        "cota TVA (%)",
        max_digits=5,
        decimal_places=2,
        choices=VAT_RATE_CHOICES,
        default=DEFAULT_VAT_RATE,
    )
    expected_date = models.DateField("data estimată")

    objects = PurchaseOrderLineQuerySet.as_manager()

    class Meta:
        verbose_name = "linie de comandă"
        verbose_name_plural = "linii de comandă"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="order_line_quantity_positive"
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0), name="order_line_price_not_negative"
            ),
        ]

    def __str__(self):
        product = self.product.code if self.product_id else "?"
        return f"{self.order} · {product} × {format_quantity(self.quantity)}"

    def get_additional_data(self):
        """Leagă intrările din jurnalul de audit de comandă: istoricul comenzii
        arată și modificările liniilor ei (vezi apps/audit/timeline.py)."""
        return {"parent": f"purchasing.purchaseorder:{self.order_id}"}

    def clean(self):
        errors = {}
        order = self._order_or_none()
        if self.product_id and not self.product.is_active and self._state.adding:
            errors["product"] = "Produsul este inactiv și nu mai poate fi ales pe documente noi."
        if order and self.expected_date and self.expected_date < order.order_date:
            errors["expected_date"] = "Data estimată nu poate fi înaintea datei comenzii."
        if order and order.is_amendable and not self._state.adding:
            errors.update(self._amendment_errors())
        if errors:
            raise ValidationError(errors)

    def _order_or_none(self):
        """Comanda liniei, chiar dacă încă nu e salvată (formularul „Comandă nouă”)."""
        try:
            return self.order
        except PurchaseOrder.DoesNotExist:
            return None

    def _amendment_errors(self):
        """După trimitere, o linie existentă se poate modifica doar controlat (I-07):
        termenul da; cantitatea doar în sus; produsul, prețul și TVA deloc."""
        original = PurchaseOrderLine.objects.get(pk=self.pk)
        errors = {}
        locked = "Nu se poate modifica după trimiterea comenzii."
        if self.product_id != original.product_id:
            errors["product"] = locked
        if self.unit_price != original.unit_price:
            errors["unit_price"] = locked
        if self.vat_rate != original.vat_rate:
            errors["vat_rate"] = locked
        if self.quantity is not None and self.quantity < original.quantity:
            errors["quantity"] = (
                f"După trimitere, cantitatea poate doar să crească (minim {original.quantity:f})."
            )
        return errors

    # --- Valori ------------------------------------------------------------------------

    @property
    def net_amount(self):
        """Valoarea fără TVA, rotunjită pe linie (așa calculează și programele de facturare)."""
        return money(self.quantity * self.unit_price)

    @property
    def vat_amount(self):
        return money(self.net_amount * self.vat_rate / 100)
