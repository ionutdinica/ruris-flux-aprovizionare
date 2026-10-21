"""Detectorul de probleme: ce întârzie, ce e blocat și pe cine privește.

    alerts = collect()                 # toate problemele deschise din aplicație
    mine = for_user(alerts, user)      # doar cele care îl privesc pe `user`

Regulile sunt cele din docs/05-reguli-business.md, §4, fiecare cu codul ei. Modulul
doar citește. Îl folosesc emailul zilnic (capitolul 8) și panoul fiecărui rol
(capitolul 9): o singură definiție pentru „întârziat” și „blocat”, deci emailul și
panoul nu se pot contrazice.

Cine primește ce: fiecare problemă spune fie un ROL (toată echipa: ex. Depozitul
pentru livrările de azi), fie anumiți UTILIZATORI (ex. responsabilul comenzii).
Administratorul nu primește rezumat: vede tot în panou și în jurnal.
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field

from django.db.models import F
from django.utils import timezone

from apps.accounts.models import User
from apps.core.dates import business_days_between
from apps.core.text import format_money, format_quantity
from apps.invoicing.models import Invoice
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.warehouse.models import Discrepancy

Role = User.Role
InvoiceStatus = Invoice.Status

# Pragurile din docs/05-reguli-business.md, §4.
DUE_SOON_DAYS = 3  # factură aprobată cu scadența în cel mult 3 zile
RATE_PENDING_BUSINESS_DAYS = 1  # în așteptarea cursului de mai mult de 1 zi lucrătoare
MATCHED_WAITING_BUSINESS_DAYS = 3  # potrivită, dar neaprobată de mai mult de 3 zile lucrătoare


class Section:
    """Secțiunile rezumatului, în ordinea afișării."""

    LATE = "late"
    BLOCKED = "blocked"
    TODAY = "today"

    TITLES = {LATE: "Întârzieri și scadențe", BLOCKED: "Blocaje", TODAY: "Azi"}
    ORDER = (LATE, BLOCKED, TODAY)


@dataclass(frozen=True)
class Alert:
    code: str  # ORDER_LATE, INVOICE_BLOCKED... (docs/05, §4)
    section: str
    key: str  # stabil de la o zi la alta: „ce e NOU” se află comparând cheile
    title: str  # documentul: „CMD-2026-0001 · Motoare Industriale SA”
    detail: str  # ce e de făcut / de ce
    url: str  # adresa din aplicație (relativă)
    roles: frozenset = field(default_factory=frozenset)
    users: frozenset = field(default_factory=frozenset)  # id-uri de utilizatori

    def concerns(self, user):
        return user.role in self.roles or user.pk in self.users


def collect(today=None):
    """Toate problemele deschise, fiecare cu cei pe care îi privește."""
    today = today or timezone.localdate()
    return [
        *late_orders(today),
        *deliveries_today(today),
        *open_discrepancies(),
        *blocked_invoices(),
        *rate_pending_invoices(today),
        *matched_waiting_invoices(today),
        *approved_invoices_due(today),
    ]


def for_user(alerts, user):
    """Problemele care îl privesc pe `user`, grupate în ordinea secțiunilor."""
    if not user.is_active:
        return []
    mine = [alert for alert in alerts if alert.concerns(user)]
    return sorted(mine, key=lambda a: (Section.ORDER.index(a.section), a.code, a.title))


def alerts_for(user, today=None):
    return for_user(collect(today), user)


# --- Comenzi și livrări ----------------------------------------------------------------------


def _pending_lines():
    """Liniile comenzilor deschise care mai au marfă de primit."""
    return (
        PurchaseOrderLine.objects.with_progress()
        .filter(order__status__in=PurchaseOrder.OPEN_STATUSES, received_qty__lt=F("quantity"))
        .select_related("order__supplier", "product")
        .order_by("order__number", "expected_date", "id")
    )


def _by_order(lines):
    grouped = defaultdict(list)
    for line in lines:
        grouped[line.order].append(line)
    return grouped.items()


def _missing(line):
    quantity = format_quantity(line.quantity - line.received_qty)
    return f"{quantity} {line.product.unit} {line.product.code}"


def late_orders(today):
    """ORDER_LATE: termen depășit, marfă încă nesosită. Responsabilul + Depozitul."""
    for order, lines in _by_order(_pending_lines().filter(expected_date__lt=today)):
        details = [
            f"{_missing(line)}, termen {line.expected_date:%d.%m}"
            f" ({_days((today - line.expected_date).days)} întârziere)"
            for line in lines
        ]
        yield Alert(
            code="ORDER_LATE",
            section=Section.LATE,
            key=f"ORDER_LATE:{order.pk}",
            title=f"{order} · {order.supplier}",
            detail="Nesosit: " + "; ".join(details) + ".",
            url=order.get_absolute_url(),
            roles=frozenset({Role.WAREHOUSE}),
            users=frozenset({order.owner_id}),
        )


def deliveries_today(today):
    """DELIVERY_EXPECTED_TODAY: ce marfă ar trebui să sosească azi. Doar Depozitul."""
    for order, lines in _by_order(_pending_lines().filter(expected_date=today)):
        yield Alert(
            code="DELIVERY_EXPECTED_TODAY",
            section=Section.TODAY,
            key=f"DELIVERY_EXPECTED_TODAY:{order.pk}:{today:%Y%m%d}",
            title=f"{order} · {order.supplier}",
            detail="Se așteaptă azi: " + "; ".join(_missing(line) for line in lines) + ".",
            url=order.get_absolute_url(),
            roles=frozenset({Role.WAREHOUSE}),
        )


def open_discrepancies():
    """DISCREPANCY_OPEN: marfă în carantină care așteaptă decizia Achizițiilor.

    O primește responsabilul comenzii; marfa venită fără comandă nu are responsabil,
    deci o primesc toți cei din Achiziții.
    """
    discrepancies = Discrepancy.objects.filter(status=Discrepancy.Status.OPEN).select_related(
        "receipt_line__product",
        "receipt_line__order_line__order",
        "receipt_line__receipt__purchase_order",
        "receipt_line__receipt__supplier",
    )
    for discrepancy in discrepancies.order_by("created_at"):
        line = discrepancy.receipt_line
        order = line.order_line.order if line.order_line_id else line.receipt.purchase_order
        product = line.product
        yield Alert(
            code="DISCREPANCY_OPEN",
            section=Section.BLOCKED,
            key=f"DISCREPANCY_OPEN:{discrepancy.pk}",
            title=f"Carantină · {product}",
            detail=(
                f"{format_quantity(discrepancy.quantity)} {product.unit} de la "
                f"{line.receipt.supplier} ({discrepancy.get_type_display().lower()}), "
                f"din {discrepancy.created_at:%d.%m}: atașează la o comandă sau returnează."
            ),
            url=discrepancy.get_absolute_url(),
            roles=frozenset() if order else frozenset({Role.PROCUREMENT}),
            users=frozenset({order.owner_id}) if order else frozenset(),
        )


# --- Facturi -------------------------------------------------------------------------------


def _invoices(status):
    return Invoice.objects.filter(status=status).select_related("supplier").order_by("number")


def _order_owners(invoice):
    """Responsabilii comenzilor facturate: ei vorbesc cu furnizorul când factura e blocată."""
    return frozenset(invoice.lines.values_list("order_line__order__owner_id", flat=True).distinct())


def blocked_invoices():
    """INVOICE_BLOCKED: Contabilitatea + responsabilii comenzilor implicate."""
    for invoice in _invoices(InvoiceStatus.BLOCKED):
        problems = invoice.problems
        detail = problems[0]["message"] if problems else "Blocată."
        if len(problems) > 1:
            detail += f" (și încă {len(problems) - 1})"
        yield Alert(
            code="INVOICE_BLOCKED",
            section=Section.BLOCKED,
            key=f"INVOICE_BLOCKED:{invoice.pk}",
            title=f"{invoice} · {invoice.supplier} · nr. {invoice.supplier_invoice_number}",
            detail=detail,
            url=invoice.get_absolute_url(),
            roles=frozenset({Role.ACCOUNTING}),
            users=_order_owners(invoice),
        )


def rate_pending_invoices(today):
    """INVOICE_RATE_PENDING: fără curs BNR de mai mult de o zi lucrătoare (BNR nu răspunde)."""
    for invoice in _invoices(InvoiceStatus.RATE_PENDING):
        waiting = business_days_between(_since(invoice), today)
        if waiting > RATE_PENDING_BUSINESS_DAYS:
            yield Alert(
                code="INVOICE_RATE_PENDING",
                section=Section.BLOCKED,
                key=f"INVOICE_RATE_PENDING:{invoice.pk}",
                title=f"{invoice} · {invoice.supplier}",
                detail=(
                    f"Așteaptă cursul BNR din {invoice.invoice_date:%d.%m.%Y} de "
                    f"{_days(waiting, 'lucrătoare')}; verifică pagina Cursuri BNR."
                ),
                url=invoice.get_absolute_url(),
                roles=frozenset({Role.ACCOUNTING}),
            )


def matched_waiting_invoices(today):
    """INVOICE_MATCHED_WAITING: potrivită, dar neaprobată de mai mult de 3 zile lucrătoare."""
    for invoice in _invoices(InvoiceStatus.MATCHED):
        waiting = business_days_between(_since(invoice), today)
        if waiting > MATCHED_WAITING_BUSINESS_DAYS:
            yield Alert(
                code="INVOICE_MATCHED_WAITING",
                section=Section.BLOCKED,
                key=f"INVOICE_MATCHED_WAITING:{invoice.pk}",
                title=f"{invoice} · {invoice.supplier}",
                detail=(
                    f"Potrivită de {_days(waiting, 'lucrătoare')}, încă neaprobată "
                    f"(scadența {invoice.due_date:%d.%m.%Y})."
                ),
                url=invoice.get_absolute_url(),
                roles=frozenset({Role.ACCOUNTING}),
            )


def approved_invoices_due(today):
    """INVOICE_OVERDUE și INVOICE_DUE_SOON: facturi aprobate de plătit."""
    limit = today + datetime.timedelta(days=DUE_SOON_DAYS)
    for invoice in _invoices(InvoiceStatus.APPROVED).filter(due_date__lte=limit):
        overdue = invoice.due_date < today
        if overdue:
            late_by = _days((today - invoice.due_date).days)
            when = f"scadența a trecut pe {invoice.due_date:%d.%m.%Y} ({late_by})"
        elif invoice.due_date == today:
            when = "scadența e azi"
        else:
            when = f"scadența pe {invoice.due_date:%d.%m.%Y}"
        code = "INVOICE_OVERDUE" if overdue else "INVOICE_DUE_SOON"
        yield Alert(
            code=code,
            section=Section.LATE,
            key=f"{code}:{invoice.pk}",
            title=f"{invoice} · {invoice.supplier}",
            detail=f"De plătit {format_money(invoice.declared_total)} {invoice.currency}: {when}.",
            url=invoice.get_absolute_url(),
            roles=frozenset({Role.ACCOUNTING}),
        )


def _since(invoice):
    """Ziua (locală) de la care factura e în statusul curent."""
    return timezone.localtime(invoice.status_changed_at).date()


def _days(count, kind=""):
    unit = "zi" if count == 1 else "zile"
    return f"{count} {unit}{' ' + kind if kind else ''}"
