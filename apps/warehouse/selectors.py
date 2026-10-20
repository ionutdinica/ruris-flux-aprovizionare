"""Interogări de citire pentru stoc (nu modifică nimic).

Stocul nu e stocat nicăieri ca număr: se calculează din registrul de mișcări,
deci nu se poate desincroniza de documentele care l-au produs.
"""

from decimal import Decimal

from django.db.models import Count, DecimalField, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from apps.catalog.models import Product
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine

from .models import Discrepancy, StockMovement

ZERO = Decimal("0")
QUANTITY_FIELD = DecimalField(max_digits=15, decimal_places=3)


def available_stock(product):
    """Stocul disponibil al unui produs: suma mișcărilor (+ intrări, − ieșiri)."""
    total = StockMovement.objects.filter(product=product).aggregate(total=Sum("quantity"))["total"]
    return total or ZERO


def quarantined_stock(product):
    """Marfa fizic în depozit, dar în carantină (discrepanțe deschise): nu e disponibilă."""
    total = Discrepancy.objects.filter(
        receipt_line__product=product, status=Discrepancy.Status.OPEN
    ).aggregate(total=Sum("quantity"))["total"]
    return total or ZERO


def products_with_stock(queryset=None):
    """Produsele, fiecare cu `stock_available` și `stock_quarantined` calculate în baza de date."""
    queryset = queryset if queryset is not None else Product.objects.all()
    movements = (
        StockMovement.objects.filter(product=OuterRef("pk"))
        .order_by()
        .values("product")
        .annotate(total=Sum("quantity"))
        .values("total")
    )
    quarantine = (
        Discrepancy.objects.filter(
            receipt_line__product=OuterRef("pk"), status=Discrepancy.Status.OPEN
        )
        .order_by()
        .values("receipt_line__product")
        .annotate(total=Sum("quantity"))
        .values("total")
    )
    return queryset.annotate(
        stock_available=Coalesce(
            Subquery(movements, output_field=QUANTITY_FIELD),
            Value(ZERO),
            output_field=QUANTITY_FIELD,
        ),
        stock_quarantined=Coalesce(
            Subquery(quarantine, output_field=QUANTITY_FIELD),
            Value(ZERO),
            output_field=QUANTITY_FIELD,
        ),
    )


def expected_deliveries():
    """Comenzile trimise care mai au marfă de primit, cu cel mai apropiat termen
    (`next_expected`) și numărul de linii în așteptare (`pending_lines`), calculate
    în baza de date. Pagina de start a Depozitului."""
    pending = PurchaseOrderLine.objects.with_progress().filter(
        order=OuterRef("pk"), received_qty__lt=F("quantity")
    )
    return (
        PurchaseOrder.objects.open()
        .annotate(
            next_expected=Subquery(pending.order_by("expected_date").values("expected_date")[:1]),
            pending_lines=Subquery(
                pending.order_by().values("order").annotate(count=Count("pk")).values("count")
            ),
        )
        .filter(next_expected__isnull=False)
        .select_related("supplier", "owner")
        .order_by("next_expected", "number")
    )
