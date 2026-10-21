"""Cifrele-cheie ale panoului, pe rol (doar citire).

Cifrele care numără PROBLEME (comenzi întârziate, facturi blocate...) vin din aceeași
listă pe care o arată panoul și emailul (apps/notifications/alerts.py): cardul și lista
de sub el nu se pot contrazice. Celelalte (comenzi deschise, sume de plată) se
calculează direct în baza de date, cu COUNT / SUM.

Permisiunile se respectă și aici: panoul Depozitului nu conține nicio sumă de bani.
"""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Sum
from django.urls import reverse

from apps.accounts.models import User
from apps.core.text import plural
from apps.invoicing.models import Invoice
from apps.purchasing.models import PurchaseOrder
from apps.warehouse.models import Discrepancy, GoodsReceipt

Role = User.Role
InvoiceStatus = Invoice.Status

PAY_SOON_DAYS = 7
MINE = "&ale_mele=1"  # filtrul „Doar ale mele” al listelor (apps/core/views.py)


@dataclass(frozen=True)
class Kpi:
    """O cifră-cheie și lista de la care provine.

    Regula: clicul pe card duce la o listă care arată EXACT ce numără cardul (testat în
    tests/test_kpi_links.py). Pentru sume, `count` = câte documente intră în sumă.
    """

    label: str
    value: object  # număr sau sumă
    url: str = ""
    hint: str = ""
    is_money: bool = False  # afișat cu 2 zecimale și „lei”
    warn_if_positive: bool = True  # evidențiat (roșu) când e diferit de zero
    count: int | None = None  # pentru sume: numărul de documente din listă

    @property
    def needs_attention(self):
        return self.warn_if_positive and bool(self.value)

    @property
    def list_count(self):
        """Câte rânduri trebuie să aibă lista la care duce cardul."""
        return self.count if self.is_money else self.value


def kpis_for(user, alerts, today):
    """Cifrele-cheie ale rolului lui `user`. `alerts` = problemele lui (sau toate, la Admin)."""
    counts = Counter(alert.code for alert in alerts)
    builders = {
        Role.PROCUREMENT: _procurement,
        Role.WAREHOUSE: _warehouse,
        Role.ACCOUNTING: _accounting,
        Role.ADMIN: _admin,
    }
    builder = builders.get(user.role)
    return builder(user, counts, today) if builder else []


def _procurement(user, counts, today):
    """Cardurile Achizițiilor numără doar ce îl privește pe utilizator: listele la care
    duc au filtrul „Doar ale mele” (aceeași regulă ca emailul și lista „De rezolvat”)."""
    orders = reverse("purchasing:order_list")
    return [
        Kpi("Comenzile mele întârziate", counts["ORDER_LATE"], f"{orders}?status=late{MINE}"),
        Kpi(
            "Marfă în carantină",
            counts["DISCREPANCY_OPEN"],
            reverse("warehouse:discrepancy_list") + f"?status=OPEN{MINE}",
            "așteaptă decizia ta",
        ),
        Kpi(
            "Facturi blocate",
            counts["INVOICE_BLOCKED"],
            reverse("invoicing:invoice_list") + f"?status=BLOCKED{MINE}",
            "pe comenzile mele",
        ),
        Kpi(
            "Comenzile mele deschise",
            PurchaseOrder.objects.open().filter(owner=user).count(),
            f"{orders}?status=open{MINE}",
            "se așteaptă marfă",
            warn_if_positive=False,
        ),
    ]


def _warehouse(user, counts, today):
    return [
        Kpi(
            "Livrări așteptate azi",
            counts["DELIVERY_EXPECTED_TODAY"],
            reverse("warehouse:expected") + "?status=today",
            warn_if_positive=False,
        ),
        Kpi(
            "Comenzi întârziate",
            counts["ORDER_LATE"],
            reverse("warehouse:expected") + "?status=late",
            "marfă care trebuia să sosească",
        ),
        Kpi(
            "Marfă în carantină",
            Discrepancy.objects.filter(status=Discrepancy.Status.OPEN).count(),
            reverse("warehouse:discrepancy_list") + "?status=OPEN",
            "nedisponibilă până decid Achizițiile",
        ),
        Kpi(
            "Recepții în ciornă",
            GoodsReceipt.objects.filter(status=GoodsReceipt.Status.DRAFT).count(),
            reverse("warehouse:receipt_list") + "?status=DRAFT",
            "neconfirmate încă",
        ),
    ]


def _to_resolve():
    return Kpi(
        "Facturi de rezolvat",
        Invoice.objects.filter(
            status__in=[InvoiceStatus.REGISTERED, InvoiceStatus.RATE_PENDING, InvoiceStatus.BLOCKED]
        ).count(),
        reverse("invoicing:invoice_list") + "?status=attention",
        "înregistrate, în așteptare, blocate",
    )


def _accounting(user, counts, today):
    invoices = reverse("invoicing:invoice_list")
    blocked = Invoice.objects.filter(status=InvoiceStatus.BLOCKED)
    pay_soon = Invoice.objects.to_pay_within(PAY_SOON_DAYS, today)
    return [
        _to_resolve(),
        Kpi(
            "Valoarea facturilor blocate",
            _total_ron(blocked),
            f"{invoices}?status=BLOCKED",
            plural(blocked.count(), "factură", "facturi"),
            is_money=True,
            count=blocked.count(),
        ),
        Kpi(
            f"De plătit în {PAY_SOON_DAYS} zile",
            _total_ron(pay_soon),
            f"{invoices}?status=pay_soon",
            plural(pay_soon.count(), "factură aprobată", "facturi aprobate"),
            is_money=True,
            warn_if_positive=False,
            count=pay_soon.count(),
        ),
        Kpi(
            "Scadențe depășite",
            Invoice.objects.overdue(today).count(),
            f"{invoices}?status=overdue",
            "neplătite",
        ),
    ]


def _admin(user, counts, today):
    """Imaginea întregii firme: câte probleme de fiecare fel sunt deschise acum."""
    invoices = reverse("invoicing:invoice_list")
    return [
        Kpi(
            "Comenzi întârziate",
            counts["ORDER_LATE"],
            reverse("purchasing:order_list") + "?status=late",
        ),
        Kpi(
            "Marfă în carantină",
            counts["DISCREPANCY_OPEN"],
            reverse("warehouse:discrepancy_list") + "?status=OPEN",
        ),
        Kpi("Facturi blocate", counts["INVOICE_BLOCKED"], f"{invoices}?status=BLOCKED"),
        _to_resolve(),
    ]


def _total_ron(invoices):
    """Suma în lei. Facturile fără curs încă (în așteptare) nu au total în lei: nu intră."""
    return invoices.aggregate(total=Sum("total_ron"))["total"] or Decimal("0")
