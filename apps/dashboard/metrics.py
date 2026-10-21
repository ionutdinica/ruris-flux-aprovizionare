"""Cifrele-cheie ale panoului, pe rol (doar citire).

Cifrele care numără PROBLEME (comenzi întârziate, facturi blocate...) vin din aceeași
listă pe care o arată panoul și emailul (apps/notifications/alerts.py): cardul și lista
de sub el nu se pot contrazice. Celelalte (comenzi deschise, sume de plată) se
calculează direct în baza de date, cu COUNT / SUM.

Permisiunile se respectă și aici: panoul Depozitului nu conține nicio sumă de bani.
"""

import datetime
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


@dataclass(frozen=True)
class Kpi:
    label: str
    value: object  # număr sau sumă
    url: str = ""
    hint: str = ""
    is_money: bool = False  # afișat cu 2 zecimale și „lei”
    warn_if_positive: bool = True  # evidențiat (roșu) când e diferit de zero

    @property
    def needs_attention(self):
        return self.warn_if_positive and bool(self.value)


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
    return [
        Kpi(
            "Comenzile mele întârziate",
            counts["ORDER_LATE"],
            reverse("purchasing:order_list") + "?status=late",
        ),
        Kpi(
            "Marfă în carantină",
            counts["DISCREPANCY_OPEN"],
            reverse("warehouse:discrepancy_list") + "?status=OPEN",
            "așteaptă decizia ta",
        ),
        Kpi(
            "Facturi blocate",
            counts["INVOICE_BLOCKED"],
            reverse("invoicing:invoice_list") + "?status=BLOCKED",
            "pe comenzile mele",
        ),
        Kpi(
            "Comenzile mele deschise",
            PurchaseOrder.objects.open().filter(owner=user).count(),
            reverse("purchasing:order_list") + "?status=open",
            "se așteaptă marfă",
            warn_if_positive=False,
        ),
    ]


def _warehouse(user, counts, today):
    return [
        Kpi(
            "Livrări așteptate azi",
            counts["DELIVERY_EXPECTED_TODAY"],
            reverse("warehouse:expected"),
            warn_if_positive=False,
        ),
        Kpi(
            "Comenzi întârziate",
            counts["ORDER_LATE"],
            reverse("warehouse:expected"),
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


def _accounting(user, counts, today):
    blocked = Invoice.objects.filter(status=InvoiceStatus.BLOCKED)
    pay_soon = Invoice.objects.filter(
        status=InvoiceStatus.APPROVED,
        due_date__lte=today + datetime.timedelta(days=PAY_SOON_DAYS),
    )
    return [
        Kpi(
            "Facturi de rezolvat",
            Invoice.objects.filter(
                status__in=[
                    InvoiceStatus.REGISTERED,
                    InvoiceStatus.RATE_PENDING,
                    InvoiceStatus.BLOCKED,
                ]
            ).count(),
            reverse("invoicing:invoice_list") + "?status=attention",
            "înregistrate, în așteptare, blocate",
        ),
        Kpi(
            "Valoarea facturilor blocate",
            _total_ron(blocked),
            reverse("invoicing:invoice_list") + "?status=BLOCKED",
            plural(blocked.count(), "factură", "facturi"),
            is_money=True,
        ),
        Kpi(
            f"De plătit în {PAY_SOON_DAYS} zile",
            _total_ron(pay_soon),
            reverse("invoicing:invoice_list") + "?status=APPROVED",
            plural(pay_soon.count(), "factură aprobată", "facturi aprobate"),
            is_money=True,
            warn_if_positive=False,
        ),
        Kpi(
            "Scadențe depășite",
            counts["INVOICE_OVERDUE"],
            reverse("invoicing:invoice_list") + "?status=overdue",
            "aprobate, neplătite",
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
        Kpi("Facturi blocate", counts["INVOICE_BLOCKED"], invoices + "?status=BLOCKED"),
        Kpi(
            "Facturi de urmărit",
            counts["INVOICE_RATE_PENDING"]
            + counts["INVOICE_MATCHED_WAITING"]
            + counts["INVOICE_OVERDUE"],
            invoices + "?status=attention",
            "fără curs, neaprobate, scadențe depășite",
        ),
    ]


def _total_ron(invoices):
    """Suma în lei. Facturile fără curs încă (în așteptare) nu au total în lei: nu intră."""
    return invoices.aggregate(total=Sum("total_ron"))["total"] or Decimal("0")
