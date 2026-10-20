"""Depozitul: recepții, carantină (discrepanțe) și registrul de stoc.

Ideea centrală: STOCUL ȘI CANTITĂȚILE RECEPȚIONATE VIN DIN ACELAȘI REGISTRU.
Fiecare intrare acceptată pe o linie de comandă e o mișcare de stoc legată de acea
linie; „recepționat” pe linia de comandă = suma mișcărilor ei (recepții + marfă
acceptată din carantină − retururi). Stocul și progresul comenzilor nu se pot
contrazice, pentru că sunt calculate din aceleași înregistrări.

Regulile (cine, când, cât) sunt în services.py; aici sunt datele și validările lor.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Product, Supplier
from apps.core.models import AppendOnlyModel, DocumentSequence, SearchableModel, TimeStampedModel
from apps.core.text import fold, format_quantity
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine

ZERO = Decimal("0")
QUANTITY = {"max_digits": 12, "decimal_places": 3}


class GoodsReceipt(SearchableModel, TimeStampedModel):
    """Recepția (NIR): ce a numărat Depozitul la sosirea unei livrări."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Ciornă"
        CONFIRMED = "CONFIRMED", "Confirmată"

    # Statusurile comenzilor pe care se poate recepționa: trimise, inclusiv cele deja
    # recepționate complet (ce mai vine e surplus și merge în carantină).
    RECEIVABLE_ORDER_STATUSES = (
        PurchaseOrder.Status.SENT,
        PurchaseOrder.Status.PARTIALLY_RECEIVED,
        PurchaseOrder.Status.RECEIVED,
    )

    # Numărul se dă la CONFIRMARE: o ciornă greșită se poate șterge fără goluri în numerotare.
    number = models.CharField(
        "număr", max_length=20, unique=True, null=True, blank=True, editable=False
    )
    supplier = models.ForeignKey(
        Supplier, verbose_name="furnizor", on_delete=models.PROTECT, related_name="receipts"
    )
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        verbose_name="comandă",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="receipts",
        help_text="Gol pentru marfă sosită fără comandă.",
    )
    receipt_date = models.DateField("data recepției", default=timezone.localdate)
    delivery_note = models.CharField("aviz / document de transport", max_length=50, blank=True)
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.DRAFT, editable=False
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="confirmată de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )
    confirmed_at = models.DateTimeField("confirmată la", null=True, blank=True, editable=False)
    notes = models.TextField("observații", blank=True)

    class Meta:
        verbose_name = "recepție"
        verbose_name_plural = "recepții"
        ordering = ["-receipt_date", "-id"]

    def __str__(self):
        return self.number or f"Recepție nouă #{self.pk}"

    def get_absolute_url(self):
        return reverse("warehouse:receipt_detail", args=[self.pk])

    def build_search_text(self):
        supplier = self.supplier.name if self.supplier_id else ""
        order = self.purchase_order.number if self.purchase_order_id else ""
        return fold(f"{self.number or ''} {supplier} {order} {self.delivery_note}")

    def assign_number(self):
        self.number = DocumentSequence.next_number("REC", self.receipt_date)

    @property
    def is_draft(self):
        return self.status == self.Status.DRAFT

    def clean(self):
        errors = {}
        if self.receipt_date and self.receipt_date > timezone.localdate():
            errors["receipt_date"] = "Data recepției nu poate fi în viitor."
        order = self.purchase_order if self.purchase_order_id else None
        if order:
            if self.supplier_id and order.supplier_id != self.supplier_id:
                errors["purchase_order"] = "Comanda aparține altui furnizor."
            elif order.status not in self.RECEIVABLE_ORDER_STATUSES:
                errors["purchase_order"] = (
                    f"Pe comanda {order} nu se mai poate recepționa "
                    f"({order.get_status_display().lower()}). Recepționează marfa fără comandă."
                )
        if errors:
            raise ValidationError(errors)


class GoodsReceiptLine(TimeStampedModel):
    receipt = models.ForeignKey(
        GoodsReceipt, verbose_name="recepție", on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(Product, verbose_name="produs", on_delete=models.PROTECT)
    order_line = models.ForeignKey(
        PurchaseOrderLine,
        verbose_name="linie de comandă",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="receipt_lines",
    )
    quantity_received = models.DecimalField(
        "cantitate numărată",
        **QUANTITY,
        validators=[MinValueValidator(ZERO, "Cantitatea nu poate fi negativă.")],
    )
    # Calculate la confirmare (docs/05-reguli-business.md §3):
    quantity_accepted = models.DecimalField(
        "acceptat în stoc", **QUANTITY, null=True, blank=True, editable=False
    )
    quantity_quarantined = models.DecimalField(
        "în carantină", **QUANTITY, null=True, blank=True, editable=False
    )
    notes = models.CharField("observații", max_length=200, blank=True)

    class Meta:
        verbose_name = "linie de recepție"
        verbose_name_plural = "linii de recepție"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity_received__gte=0), name="receipt_line_quantity_not_negative"
            ),
            # O linie de comandă apare cel mult o dată pe aceeași recepție.
            models.UniqueConstraint(
                fields=["receipt", "order_line"],
                condition=Q(order_line__isnull=False),
                name="unique_order_line_per_receipt",
            ),
        ]

    def __str__(self):
        product = self.product.code if self.product_id else "?"
        return f"{self.receipt} · {product} × {format_quantity(self.quantity_received)}"

    def get_additional_data(self):
        """Modificările liniei apar în istoricul recepției (vezi apps/audit/timeline.py)."""
        return {"parent": f"warehouse.goodsreceipt:{self.receipt_id}"}

    def clean(self):
        if not self.order_line_id:
            return
        receipt = self.receipt
        if receipt.purchase_order_id != self.order_line.order_id:
            raise ValidationError({"order_line": "Linia nu aparține comenzii recepționate."})
        if self.product_id and self.product_id != self.order_line.product_id:
            raise ValidationError({"product": "Produsul diferă de cel de pe linia de comandă."})


class Discrepancy(TimeStampedModel):
    """Marfă în carantină: primită, dar neacoperită de o comandă (I-11). Achizițiile
    decid: o atașează la o linie de comandă (intră în stoc) sau o returnează (I-12)."""

    class Type(models.TextChoices):
        UNORDERED = "UNORDERED", "Marfă necomandată"
        OVER_DELIVERY = "OVER_DELIVERY", "Livrare peste comandă"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Deschisă"
        RESOLVED = "RESOLVED", "Rezolvată"

    class Resolution(models.TextChoices):
        ATTACHED = "ATTACHED", "Atașată la comandă (intrată în stoc)"
        RETURNED = "RETURNED", "Returnată furnizorului"

    receipt_line = models.OneToOneField(
        GoodsReceiptLine,
        verbose_name="linie de recepție",
        on_delete=models.PROTECT,
        related_name="discrepancy",
    )
    type = models.CharField("tip", max_length=20, choices=Type.choices)
    quantity = models.DecimalField("cantitate în carantină", **QUANTITY)
    status = models.CharField("status", max_length=10, choices=Status.choices, default=Status.OPEN)
    resolution = models.CharField(
        "rezolvare", max_length=10, choices=Resolution.choices, blank=True
    )
    attached_order_line = models.ForeignKey(
        PurchaseOrderLine,
        verbose_name="atașată la linia",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attached_discrepancies",
    )
    resolution_note = models.TextField("observații la rezolvare", blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="rezolvată de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    resolved_at = models.DateTimeField("rezolvată la", null=True, blank=True)

    class Meta:
        verbose_name = "discrepanță"
        verbose_name_plural = "discrepanțe"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="discrepancy_quantity_positive"
            )
        ]

    def __str__(self):
        return f"{self.get_type_display()} · {self.product.code} × {format_quantity(self.quantity)}"

    def get_absolute_url(self):
        return reverse("warehouse:discrepancy_detail", args=[self.pk])

    def get_additional_data(self):
        """Apariția și rezolvarea discrepanței apar și în istoricul recepției."""
        return {"parent": f"warehouse.goodsreceipt:{self.receipt_line.receipt_id}"}

    @property
    def product(self):
        return self.receipt_line.product

    @property
    def receipt(self):
        return self.receipt_line.receipt

    @property
    def supplier(self):
        return self.receipt_line.receipt.supplier

    @property
    def is_open(self):
        return self.status == self.Status.OPEN


class StockMovement(AppendOnlyModel):
    """Registrul de stoc: fiecare intrare și ieșire de marfă. Nu se modifică și nu se
    șterge; o greșeală se corectează printr-o mișcare nouă (ajustare), vizibilă.

    Stocul disponibil al unui produs = suma cantităților (+ intrări, − ieșiri).
    """

    class Type(models.TextChoices):
        RECEIPT = "RECEIPT", "Recepție"
        DISCREPANCY_ACCEPTED = "DISCREPANCY_ACCEPTED", "Intrare din carantină"
        CONSUMPTION = "CONSUMPTION", "Consum"
        SUPPLIER_RETURN = "SUPPLIER_RETURN", "Retur la furnizor"
        ADJUSTMENT = "ADJUSTMENT", "Ajustare de inventar"

    INBOUND = (Type.RECEIPT, Type.DISCREPANCY_ACCEPTED)
    OUTBOUND = (Type.CONSUMPTION, Type.SUPPLIER_RETURN)
    # Mișcările care pot fi legate de o linie de comandă: din ele se calculează
    # cantitatea recepționată a liniei (vezi PurchaseOrderLine.objects.with_progress()).
    ORDER_LINE_TYPES = (Type.RECEIPT, Type.DISCREPANCY_ACCEPTED, Type.SUPPLIER_RETURN)

    product = models.ForeignKey(
        Product, verbose_name="produs", on_delete=models.PROTECT, related_name="stock_movements"
    )
    type = models.CharField("tip", max_length=25, choices=Type.choices)
    quantity = models.DecimalField("cantitate", **QUANTITY)  # cu semn: + intrare, − ieșire
    date = models.DateField("data", default=timezone.localdate)
    receipt_line = models.ForeignKey(
        GoodsReceiptLine, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    order_line = models.ForeignKey(
        PurchaseOrderLine,
        verbose_name="linie de comandă",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_movements",
    )
    discrepancy = models.ForeignKey(
        Discrepancy, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    reason = models.CharField("motiv", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="operat de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField("înregistrată la", auto_now_add=True)

    class Meta:
        verbose_name = "mișcare de stoc"
        verbose_name_plural = "mișcări de stoc"
        ordering = ["-date", "-id"]
        constraints = [
            # Semnul cantității trebuie să corespundă tipului mișcării.
            models.CheckConstraint(
                condition=(
                    Q(type__in=["RECEIPT", "DISCREPANCY_ACCEPTED"], quantity__gt=0)
                    | Q(type__in=["CONSUMPTION", "SUPPLIER_RETURN"], quantity__lt=0)
                    | (Q(type="ADJUSTMENT") & ~Q(quantity=0))
                ),
                name="stock_movement_sign_matches_type",
            ),
            # Doar recepțiile, intrările din carantină și retururile țin de o linie de comandă.
            models.CheckConstraint(
                condition=(
                    Q(order_line__isnull=True)
                    | Q(type__in=["RECEIPT", "DISCREPANCY_ACCEPTED", "SUPPLIER_RETURN"])
                ),
                name="stock_movement_order_line_only_for_order_types",
            ),
        ]
        indexes = [models.Index(fields=["product", "date"])]

    def __str__(self):
        return (
            f"{self.get_type_display()} · {self.product.code} "
            f"{format_quantity(self.quantity, sign=True)}"
        )
