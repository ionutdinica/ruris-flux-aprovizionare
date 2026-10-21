"""Datele graficelor din panou (doar citire). Desenarea: static/js/dashboard.js (Chart.js).

Fiecare funcție întoarce un `Chart`: etichete, serii și un rezumat în cuvinte, afișat
lângă grafic (informația rămâne citibilă și fără desen). Datele ajung în pagină prin
`json_script`, modul sigur de a le da JavaScript-ului.
"""

import datetime
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from django.db.models import (
    Case,
    Count,
    DecimalField,
    F,
    IntegerField,
    OuterRef,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.core.text import format_money, format_quantity
from apps.invoicing.models import Invoice
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.warehouse.models import StockMovement
from apps.warehouse.selectors import products_with_stock

ON_TIME_PERIOD_DAYS = 90  # livrări la timp: liniile cu termenul în ultimele 90 de zile
LATE_TREND_DAYS = 30
DELIVERY_HORIZON_DAYS = 14
STOCK_TOP_PRODUCTS = 10
PAYMENT_WEEKS = 6

# Culorile graficelor (paleta Bootstrap, aceeași ca în restul aplicației).
GREEN, RED, BLUE, ORANGE, GREY, DARK = (
    "#198754",
    "#dc3545",
    "#1f3a5f",
    "#fd7e14",
    "#adb5bd",
    "#212529",
)


@dataclass
class Chart:
    id: str
    title: str
    kind: str  # "bar", "line", "doughnut"
    labels: list
    datasets: list  # [{"label": ..., "data": [...], "color": ... sau [...]}]
    summary: str = ""  # concluzia, în cuvinte
    unit: str = ""  # "%", "lei" sau "" (bucăți, comenzi)
    horizontal: bool = False
    stacked: bool = False
    empty_message: str = "Încă nu există date pentru acest grafic."
    # „Zero peste tot” = nimic de arătat (ex. nicio comandă întârziată)? La procente
    # (livrări la timp), 0% e o valoare reală, importantă: graficul trebuie afișat.
    zero_is_empty: bool = True
    rows: list = field(default_factory=list)  # tabelul „Vezi cifrele”: [(etichetă, valoare)]

    @property
    def element_id(self):
        """Id-ul elementului <script> cu datele (json_script) și al graficului care le citește."""
        return f"chart-{self.id}"

    @property
    def is_empty(self):
        if not self.labels:
            return True
        if not self.zero_is_empty:
            return False
        return not any(any(value for value in dataset["data"]) for dataset in self.datasets)

    def as_json(self):
        return asdict(self)


def _decimal(digits=3):
    return DecimalField(max_digits=15, decimal_places=digits)


# --- Achiziții: furnizorii și întârzierile ---------------------------------------------------


def on_time_by_supplier(today):
    """Ce procent din liniile cu termenul în ultimele 90 de zile au sosit INTEGRAL până la
    termen (inclusiv). O livrare parțială la termen nu e „la timp”. Liniile al căror
    termen nu a trecut încă nu se numără."""
    received_by_due = (
        StockMovement.objects.filter(order_line=OuterRef("pk"), date__lte=OuterRef("expected_date"))
        .order_by()
        .values("order_line")
        .annotate(total=Sum("quantity"))
        .values("total")
    )
    rows = (
        PurchaseOrderLine.objects.filter(
            expected_date__lt=today,
            expected_date__gte=today - datetime.timedelta(days=ON_TIME_PERIOD_DAYS),
        )
        .exclude(order__status__in=[PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.CANCELLED])
        .annotate(
            by_due=Coalesce(Subquery(received_by_due, output_field=_decimal()), Value(Decimal(0))),
            on_time=Case(
                When(by_due__gte=F("quantity"), then=1), default=0, output_field=IntegerField()
            ),
        )
        .values("order__supplier__name")
        .annotate(lines=Count("pk"), on_time_lines=Sum("on_time"))
        .order_by("order__supplier__name")
    )
    stats = [(row["order__supplier__name"], row["on_time_lines"], row["lines"]) for row in rows]
    stats.sort(key=lambda s: (s[1] / s[2], s[0]))  # cei mai puțin punctuali primii
    percents = [round(100 * on_time / lines) for _, on_time, lines in stats]
    summary = ""
    if stats:
        worst = stats[0]
        summary = (
            f"Cel mai puțin punctual: {worst[0]}, {worst[1]} din {worst[2]} linii la timp. "
            f"Ultimele {ON_TIME_PERIOD_DAYS} de zile; „la timp” = sosit integral până la termen."
        )
    return Chart(
        id="on-time",
        title="Livrări la timp, pe furnizor",
        kind="bar",
        labels=[name for name, _, _ in stats],
        datasets=[
            {
                "label": "% linii la timp",
                "data": percents,
                "color": [GREEN if p >= 90 else ORANGE if p >= 70 else RED for p in percents],
            }
        ],
        summary=summary,
        unit="%",
        zero_is_empty=False,
        horizontal=True,
        empty_message="Nicio linie de comandă cu termenul în ultimele 90 de zile.",
        rows=[
            (name, f"{on_time} din {lines} ({p}%)")
            for (name, on_time, lines), p in zip(stats, percents, strict=True)
        ],
    )


def late_orders_trend(today):
    """Câte comenzi erau întârziate în fiecare din ultimele 30 de zile.

    Nu salvăm „poze” zilnice: registrul de stoc nu se modifică niciodată, deci pentru
    orice zi din trecut se poate calcula exact ce se recepționase până atunci. O comandă
    e întârziată în ziua D dacă era trimisă și avea o linie cu termenul înainte de D,
    nerecepționată integral până la sfârșitul zilei D. Simplificare: comenzile închise
    sau anulate între timp nu mai sunt numărate (data închiderii nu e păstrată separat).
    """
    start = today - datetime.timedelta(days=LATE_TREND_DAYS - 1)
    lines = list(
        PurchaseOrderLine.objects.filter(
            order__status__in=PurchaseOrder.AMENDABLE_STATUSES,
            order__sent_at__isnull=False,
            expected_date__lt=today,
        ).values("pk", "order_id", "quantity", "expected_date", "order__sent_at")
    )
    received = defaultdict(list)  # linie → [(data, cantitate)]
    for movement in StockMovement.objects.filter(order_line__in=[line["pk"] for line in lines]):
        received[movement.order_line_id].append((movement.date, movement.quantity))

    days = [start + datetime.timedelta(days=n) for n in range(LATE_TREND_DAYS)]
    counts = []
    for day in days:
        late = {
            line["order_id"]
            for line in lines
            if line["expected_date"] < day
            and timezone.localtime(line["order__sent_at"]).date() <= day
            and sum(q for d, q in received[line["pk"]] if d <= day) < line["quantity"]
        }
        counts.append(len(late))

    summary = (
        f"Azi: {_count(counts[-1], 'comandă întârziată', 'comenzi întârziate')}; "
        f"acum {LATE_TREND_DAYS} de zile: {counts[0]}."
    )
    return Chart(
        id="late-trend",
        title=f"Comenzi întârziate, ultimele {LATE_TREND_DAYS} de zile",
        kind="line",
        labels=[f"{day:%d.%m}" for day in days],
        datasets=[{"label": "Comenzi întârziate", "data": counts, "color": RED}],
        summary=summary,
        empty_message="Nicio comandă întârziată în ultimele 30 de zile.",
        rows=[(f"{day:%d.%m.%Y}", count) for day, count in zip(days, counts, strict=True)],
    )


# --- Depozit: ce vine și ce e pe stoc ---------------------------------------------------------


def deliveries_ahead(today):
    """Câte comenzi au marfă de primit în fiecare din următoarele 14 zile (plus cele
    întârziate), ca Depozitul să-și planifice oamenii și spațiul. Fără valori."""
    pending = PurchaseOrderLine.objects.with_progress().filter(
        order__status__in=PurchaseOrder.OPEN_STATUSES, received_qty__lt=F("quantity")
    )
    horizon = today + datetime.timedelta(days=DELIVERY_HORIZON_DAYS - 1)
    late = pending.filter(expected_date__lt=today).values("order").distinct().count()
    per_day = dict(
        pending.filter(expected_date__gte=today, expected_date__lte=horizon)
        .values("expected_date")
        .annotate(orders=Count("order", distinct=True))
        .values_list("expected_date", "orders")
    )
    days = [today + datetime.timedelta(days=n) for n in range(DELIVERY_HORIZON_DAYS)]
    labels = ["Întârziate"] + [("Azi" if day == today else _short_day(day)) for day in days]
    data = [late] + [per_day.get(day, 0) for day in days]
    busiest = max(days, key=lambda d: per_day.get(d, 0))
    expected = _count(sum(data[1:]), "livrare așteptată", "livrări așteptate")
    summary = f"{expected} în următoarele {DELIVERY_HORIZON_DAYS} zile"
    if per_day:
        summary += f"; cea mai aglomerată zi: {busiest:%d.%m} ({per_day[busiest]})"
    summary += f"; {_count(late, 'întârziată', 'întârziate')}."
    return Chart(
        id="deliveries",
        title=f"Livrări așteptate, următoarele {DELIVERY_HORIZON_DAYS} zile",
        kind="bar",
        labels=labels,
        datasets=[
            {"label": "Comenzi", "data": data, "color": [RED] + [BLUE] * DELIVERY_HORIZON_DAYS}
        ],
        summary=summary,
        empty_message="Nicio livrare așteptată.",
        rows=list(zip(labels, data, strict=True)),
    )


def stock_by_product(today):
    """Produsele cu cel mai mult stoc: disponibil și în carantină (bucăți, fără valori)."""
    products = [
        product
        for product in products_with_stock().order_by("code")
        if product.stock_available or product.stock_quarantined
    ]
    products.sort(key=lambda p: -(p.stock_available + p.stock_quarantined))
    top = products[:STOCK_TOP_PRODUCTS]
    return Chart(
        id="stock",
        title="Stoc pe produs",
        kind="bar",
        labels=[f"{p.code}" for p in top],
        datasets=[
            {"label": "Disponibil", "data": [float(p.stock_available) for p in top], "color": BLUE},
            {
                "label": "Carantină",
                "data": [float(p.stock_quarantined) for p in top],
                "color": ORANGE,
            },
        ],
        summary=(
            f"Primele {len(top)} produse după cantitate"
            + (f", din {len(products)} cu stoc." if products else ".")
        ),
        horizontal=True,
        stacked=True,
        empty_message="Nu există încă stoc.",
        rows=[
            (
                f"{p.code} {p.name}",
                f"{_qty(p.stock_available)} disponibil, {_qty(p.stock_quarantined)} carantină",
            )
            for p in top
        ],
    )


# --- Contabilitate: bani -------------------------------------------------------------------


def invoices_by_status(today):
    """Valoarea în lei a facturilor neplătite, pe status. Fără cele respinse sau plătite.
    Facturile în așteptarea cursului nu au încă valoare în lei: apar doar ca număr."""
    statuses = [
        Invoice.Status.MATCHED,
        Invoice.Status.APPROVED,
        Invoice.Status.BLOCKED,
        Invoice.Status.REGISTERED,
    ]
    totals = dict(
        Invoice.objects.filter(status__in=statuses)
        .values("status")
        .annotate(total=Sum("total_ron"))
        .values_list("status", "total")
    )
    colors = {
        Invoice.Status.MATCHED: GREEN,
        Invoice.Status.APPROVED: BLUE,
        Invoice.Status.BLOCKED: RED,
        Invoice.Status.REGISTERED: GREY,
    }
    values = [float(totals.get(status) or 0) for status in statuses]
    pending = Invoice.objects.filter(status=Invoice.Status.RATE_PENDING).count()
    summary = f"Total neplătit: {format_money(sum(values))} lei."
    if pending:
        waiting = _count(pending, "factură", "facturi")
        summary += f" Plus {waiting} în așteptarea cursului BNR (fără valoare în lei încă)."
    return Chart(
        id="invoices",
        title="Facturi neplătite, pe status (lei)",
        kind="doughnut",
        labels=[Invoice.Status(status).label for status in statuses],
        datasets=[{"label": "lei", "data": values, "color": [colors[s] for s in statuses]}],
        summary=summary,
        unit="lei",
        empty_message="Nicio factură neplătită.",
        rows=[
            (Invoice.Status(status).label, f"{format_money(value)} lei")
            for status, value in zip(statuses, values, strict=True)
        ],
    )


def payments_by_week(today):
    """Facturile aprobate, de plătit pe săptămâni (după scadență), plus cele depășite."""
    monday = today - datetime.timedelta(days=today.weekday())
    weeks = [monday + datetime.timedelta(weeks=n) for n in range(PAYMENT_WEEKS)]
    approved = Invoice.objects.filter(status=Invoice.Status.APPROVED)
    overdue = approved.filter(due_date__lt=today).aggregate(total=Sum("total_ron"))["total"]
    data = [float(overdue or 0)]
    for week in weeks:
        start = max(week, today)
        end = week + datetime.timedelta(days=6)
        total = approved.filter(due_date__gte=start, due_date__lte=end).aggregate(
            total=Sum("total_ron")
        )["total"]
        data.append(float(total or 0))
    labels = ["Depășite"] + [
        ("Săptămâna aceasta" if week == monday else f"Săpt. {week:%d.%m}") for week in weeks
    ]
    return Chart(
        id="payments",
        title="Plăți de făcut, pe săptămâni (lei)",
        kind="bar",
        labels=labels,
        datasets=[{"label": "lei", "data": data, "color": [RED] + [BLUE] * PAYMENT_WEEKS}],
        summary=f"De plătit în următoarele {PAYMENT_WEEKS} săptămâni: "
        f"{format_money(sum(data[1:]))} lei; scadențe depășite: {format_money(data[0])} lei.",
        unit="lei",
        empty_message="Nicio factură aprobată de plătit.",
        rows=[
            (label, f"{format_money(value)} lei") for label, value in zip(labels, data, strict=True)
        ],
    )


# strftime("%a") ar da zilele în engleză (Mon, Tue), indiferent de limba aplicației.
WEEKDAYS = ("lun", "mar", "mie", "joi", "vin", "sâm", "dum")


def _count(number, singular, plural):
    """„1 comandă întârziată”, „3 comenzi întârziate” (acordul în română)."""
    return f"{number} {singular if number == 1 else plural}"


def _qty(value):
    """Cantitate în format românesc: 10.000 → „10”, 2.5 → „2,5” (nu „10.000” = zece mii)."""
    return format_quantity(value).replace(".", ",")


def _short_day(day):
    return f"{WEEKDAYS[day.weekday()]} {day:%d.%m}"


# --- Ce grafice vede fiecare rol --------------------------------------------------------------

CHARTS_BY_PERMISSION = [
    # (permisiunea necesară, graficele) — Depozitul nu primește niciun grafic cu bani.
    ("orders.edit", [on_time_by_supplier, late_orders_trend]),
    ("receipts.edit", [deliveries_ahead, stock_by_product]),
    ("invoices.edit", [invoices_by_status, payments_by_week]),
]


def charts_for(user, today):
    """Graficele pe care le vede `user`, fără dubluri (Adminul le vede pe toate)."""
    builders = []
    for permission, chart_builders in CHARTS_BY_PERMISSION:
        if user.can(permission):
            builders += [b for b in chart_builders if b not in builders]
    return [build(today) for build in builders]
