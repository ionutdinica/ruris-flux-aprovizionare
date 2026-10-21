"""Potrivirea în 3 direcții: factură ↔ comandă ↔ recepție (docs/05-reguli-business.md, §1).

    problems = find_problems(invoice)    # [] = potrivită; altfel, toate motivele

Motorul NU schimbă nimic: doar citește și raportează. Cine decide statusul facturii
pe baza rezultatului e services.py. Așa regulile se pot testa izolat și se pot rula
oricând (la validare, la o recepție nouă, la un retur), fără efecte secundare.

Se raportează TOATE motivele deodată, nu doar primul: contabilul vede dintr-o privire
tot ce e de lămurit cu furnizorul.
"""

from collections import defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal

from django.conf import settings
from django.db.models import Q, Sum

from apps.core.text import format_money, format_quantity
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine

from .models import Invoice, InvoiceLine

# Diferența de rotunjire acceptată la totaluri, în moneda facturii (I-22).
TOTAL_TOLERANCE = Decimal("0.05")


class Code:
    """Codurile motivelor de blocare, aceleași în documentație, teste și interfață."""

    SUPPLIER_MISMATCH = "SUPPLIER_MISMATCH"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    ORDER_NOT_OPEN = "ORDER_NOT_OPEN"
    TOTAL_MISMATCH = "TOTAL_MISMATCH"
    DUPLICATE_LINE = "DUPLICATE_LINE"
    NOT_RECEIVED = "NOT_RECEIVED"
    OVER_ORDERED = "OVER_ORDERED"
    PRICE_MISMATCH = "PRICE_MISMATCH"

    # Etichete scurte, pentru jurnal, filtre și rapoarte.
    LABELS = {
        SUPPLIER_MISMATCH: "alt furnizor",
        CURRENCY_MISMATCH: "altă monedă",
        ORDER_NOT_OPEN: "comandă anulată / ciornă",
        TOTAL_MISMATCH: "totaluri diferite",
        DUPLICATE_LINE: "linie dublată",
        NOT_RECEIVED: "marfă nesosită",
        OVER_ORDERED: "peste cantitatea comandată",
        PRICE_MISMATCH: "preț diferit",
    }


@dataclass(frozen=True)
class Problem:
    code: str
    message: str
    order_line: int | None = None  # linia de comandă vizată, pentru evidențiere în tabel

    def as_dict(self):
        return asdict(self)


def find_problems(invoice):
    """Toate motivele pentru care factura nu poate fi plătită așa cum e."""
    lines = list(
        invoice.lines.select_related("order_line__order__supplier", "order_line__product").order_by(
            "id"
        )
    )
    return [
        *_header_problems(invoice, lines),
        *_total_problems(invoice, lines),
        *_line_problems(invoice, lines),
    ]


# --- Antet: furnizor, monedă, starea comenzilor -------------------------------------------


def _header_problems(invoice, lines):
    problems = []
    orders = {line.order_line.order_id: line.order_line.order for line in lines}
    for order in sorted(orders.values(), key=lambda o: o.number):
        if order.supplier_id != invoice.supplier_id:
            problems.append(
                Problem(
                    Code.SUPPLIER_MISMATCH,
                    f"Comanda {order} este de la alt furnizor ({order.supplier}).",
                )
            )
        if order.currency != invoice.currency:
            problems.append(
                Problem(
                    Code.CURRENCY_MISMATCH,
                    f"Factura este în {invoice.currency}, comanda {order} este în "
                    f"{order.currency}.",
                )
            )
        if order.status in (PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.CANCELLED):
            problems.append(
                Problem(
                    Code.ORDER_NOT_OPEN,
                    f"Comanda {order} este {order.get_status_display().lower()}.",
                )
            )
    return problems


# --- Totaluri: declarat (de pe hârtie) vs. calculat (din linii) ---------------------------


def _total_problems(invoice, lines):
    net = sum((line.net_amount for line in lines), Decimal("0"))
    vat = sum((line.vat_amount for line in lines), Decimal("0"))
    comparisons = [
        ("Totalul fără TVA", invoice.declared_net, net),
        ("TVA-ul", invoice.declared_vat, vat),
        ("Totalul de plată", invoice.declared_total, net + vat),
    ]
    return [
        Problem(
            Code.TOTAL_MISMATCH,
            f"{label} declarat ({format_money(declared)} {invoice.currency}) diferă de cel "
            f"calculat din linii ({format_money(computed)} {invoice.currency}).",
        )
        for label, declared, computed in comparisons
        if abs(declared - computed) > TOTAL_TOLERANCE
    ]


# --- Linii: cantități și prețuri ----------------------------------------------------------


def _line_problems(invoice, lines):
    by_order_line = defaultdict(list)
    for line in lines:
        by_order_line[line.order_line_id].append(line)

    progress = {
        ol.pk: ol
        for ol in PurchaseOrderLine.objects.with_progress()
        .select_related("product", "order")
        .filter(pk__in=by_order_line)
    }
    elsewhere = invoiced_elsewhere(invoice, by_order_line)

    problems = []
    for order_line_id, invoice_lines in by_order_line.items():
        order_line = progress[order_line_id]
        product = order_line.product
        unit = product.unit

        if len(invoice_lines) > 1:
            problems.append(
                Problem(
                    Code.DUPLICATE_LINE,
                    f"{product}: linia din comanda {order_line.order} apare de "
                    f"{len(invoice_lines)} ori pe factură.",
                    order_line_id,
                )
            )

        here = sum(line.quantity for line in invoice_lines)
        invoiced = here + elsewhere.get(order_line_id, Decimal("0"))
        earlier = invoiced - here
        before = f" (din care {_qty(earlier)} pe facturi anterioare)" if earlier else ""

        if invoiced > order_line.received_qty:
            missing = invoiced - order_line.received_qty
            problems.append(
                Problem(
                    Code.NOT_RECEIVED,
                    f"{product}: facturat {_qty(invoiced)} {unit}{before}, recepționat doar "
                    f"{_qty(order_line.received_qty)} {unit}: {_qty(missing)} {unit} nesosite.",
                    order_line_id,
                )
            )
        if invoiced > order_line.quantity:
            problems.append(
                Problem(
                    Code.OVER_ORDERED,
                    f"{product}: facturat {_qty(invoiced)} {unit}{before}, comandat "
                    f"{_qty(order_line.quantity)} {unit}.",
                    order_line_id,
                )
            )

        for line in invoice_lines:
            problem = _price_problem(invoice, line, order_line)
            if problem:
                problems.append(problem)
    return problems


def _price_problem(invoice, line, order_line):
    ordered = order_line.unit_price
    tolerance = ordered * settings.PRICE_TOLERANCE_PERCENT / 100
    if abs(line.unit_price - ordered) <= tolerance:
        return None
    if ordered:
        percent = (line.unit_price - ordered) / ordered * 100
        difference = f" ({percent:+.1f}%)".replace(".", ",")
    else:
        difference = ""
    return Problem(
        Code.PRICE_MISMATCH,
        f"{order_line.product}: preț {_price(line.unit_price)} {invoice.currency} față de "
        f"{_price(ordered)} {order_line.order.currency} în comanda {order_line.order}"
        f"{difference}.",
        order_line.pk,
    )


def invoiced_elsewhere(invoice, order_line_ids):
    """Cât s-a facturat deja pe aceste linii de comandă, pe ALTE facturi: {linie: cantitate}.

    Regula „primul venit, primul servit” (docs/05-reguli-business.md, §1): contează
    facturile aprobate sau plătite (decizia de plată e deja luată) și facturile
    potrivite înregistrate ÎNAINTEA acesteia. Astfel două facturi nu pot fi potrivite
    simultan pe aceeași marfă (protecție la dublă plată), iar la o reverificare
    rezultatul nu depinde de ordinea în care sunt reverificate.
    """
    counted = Q(invoice__status__in=(Invoice.Status.APPROVED, Invoice.Status.PAID)) | Q(
        invoice__status=Invoice.Status.MATCHED, invoice__id__lt=invoice.pk
    )
    rows = (
        InvoiceLine.objects.filter(counted, order_line_id__in=order_line_ids)
        .exclude(invoice=invoice)
        .values("order_line_id")
        .annotate(total=Sum("quantity"))
    )
    return {row["order_line_id"]: row["total"] for row in rows}


def _qty(value):
    return format_quantity(value).replace(".", ",")


def _price(value):
    """Prețul exact, cu cel puțin 2 zecimale: 10,5 → „10,50”, 1250 → „1.250,00”, 2,125 → „2,125”."""
    whole, _, decimals = format_quantity(value).partition(".")
    grouped = format_money(Decimal(whole))[:-3]  # „1.250,00” → „1.250”
    return f"{grouped},{decimals.ljust(2, '0')}"
