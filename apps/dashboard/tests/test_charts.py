"""Datele graficelor: definițiile din docs (la timp, întârziat), pe zile precise."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.catalog.tests.factories import SupplierFactory
from apps.dashboard import charts
from apps.invoicing.models import Invoice
from apps.invoicing.services import approve_invoice
from apps.invoicing.tests.scenarios import validated
from apps.notifications.alerts import collect
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.warehouse import services as warehouse
from apps.warehouse.models import GoodsReceipt, GoodsReceiptLine
from apps.warehouse.tests.scenarios import receive, sent_order

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def day(offset):
    return TODAY + datetime.timedelta(days=offset)


def order_due(offset, *quantities, supplier=None, sent=-30):
    """Comandă trimisă acum `sent` zile, cu termenul liniilor peste `offset` zile."""
    order = sent_order(*quantities, supplier=supplier)
    sent_at = timezone.make_aware(datetime.datetime.combine(day(sent), datetime.time(9)))
    PurchaseOrder.objects.filter(pk=order.pk).update(order_date=day(sent), sent_at=sent_at)
    PurchaseOrderLine.objects.filter(order=order).update(expected_date=day(offset))
    return PurchaseOrder.objects.get(pk=order.pk)


def receive_on(order, user, offset, quantity):
    """Recepție datată în trecut (data recepției = data mișcării de stoc)."""
    receipt = GoodsReceipt.objects.create(
        supplier=order.supplier, purchase_order=order, receipt_date=day(offset)
    )
    line = order.lines.get()
    GoodsReceiptLine.objects.create(
        receipt=receipt, product=line.product, order_line=line, quantity_received=Decimal(quantity)
    )
    warehouse.confirm_receipt(receipt, user)


# --- Livrări la timp ------------------------------------------------------------------------------


def test_on_time_means_complete_by_the_due_date(warehouse_user):
    punctual = SupplierFactory(name="Punctual SRL")
    late = SupplierFactory(name="Întârziat SRL")

    on_time = order_due(-10, "5", supplier=punctual)
    receive_on(on_time, warehouse_user, -10, "5")  # integral, chiar în ziua termenului
    partial = order_due(-8, "10", supplier=late)
    receive_on(partial, warehouse_user, -9, "6")  # parțial la termen...
    receive_on(partial, warehouse_user, -2, "4")  # ...restul după: NU e la timp
    never = order_due(-5, "3", supplier=late)  # nesosit deloc
    order_due(5, "3", supplier=late)  # termenul nu a venit: nu se numără
    old = order_due(-100, "3", supplier=late)  # în afara celor 90 de zile
    receive_on(old, warehouse_user, -100, "3")
    assert never.status == PurchaseOrder.Status.SENT

    chart = charts.on_time_by_supplier(TODAY)

    assert chart.labels == ["Întârziat SRL", "Punctual SRL"]  # cel mai puțin punctual primul
    assert chart.datasets[0]["data"] == [0, 100]
    assert chart.rows[0] == ("Întârziat SRL", "0 din 2 (0%)")
    assert "Cel mai puțin punctual: Întârziat SRL" in chart.summary


# --- Evoluția întârzierilor, reconstruită din registru ----------------------------------------


def test_late_trend_is_rebuilt_from_the_stock_ledger(warehouse_user):
    """Termen acum 5 zile, marfa sosită acum 2 zile: întârziată în zilele -4 și -3."""
    order = order_due(-5, "10", sent=-10)
    receive_on(order, warehouse_user, -2, "10")

    chart = charts.late_orders_trend(TODAY)
    per_day = dict(chart.rows)

    late_days = [label for label, count in per_day.items() if count]
    assert late_days == [f"{day(-4):%d.%m.%Y}", f"{day(-3):%d.%m.%Y}"]


def test_late_trend_today_matches_the_alerts(warehouse_user):
    """Ultimul punct al graficului = comenzile întârziate din lista „De rezolvat”."""
    order_due(-3, "10")
    partially = order_due(-1, "4")
    receive(partially, warehouse_user, "1")
    order_due(2, "1")  # încă în termen

    chart = charts.late_orders_trend(TODAY)

    late_now = [alert for alert in collect(TODAY) if alert.code == "ORDER_LATE"]
    assert chart.datasets[0]["data"][-1] == len(late_now) == 2


def test_order_sent_later_was_not_late_before(warehouse_user):
    """Înainte de trimitere, o comandă nu poate fi „întârziată” (nici nu exista pentru furnizor)."""
    order_due(-20, "1", sent=-3)

    counts = charts.late_orders_trend(TODAY).datasets[0]["data"]

    assert counts[-5] == 0 and counts[-3] == 1


# --- Depozit ----------------------------------------------------------------------------------


def test_deliveries_ahead(warehouse_user):
    order_due(-1, "1")  # întârziată
    order_due(0, "1")  # azi
    order_due(2, "1", "1")  # două linii, aceeași comandă: o singură livrare
    order_due(30, "1")  # dincolo de orizont

    chart = charts.deliveries_ahead(TODAY)

    data = chart.datasets[0]["data"]
    assert chart.labels[:2] == ["Întârziate", "Azi"]
    assert data[:4] == [1, 1, 0, 1]
    assert sum(data) == 3
    assert all(label.split()[0] in charts.WEEKDAYS for label in chart.labels[2:])  # în română


def test_stock_by_product(warehouse_user):
    small = sent_order("2")
    receive(small, warehouse_user, "2")
    big = sent_order("10")
    receive(big, warehouse_user, "12")  # 10 disponibil + 2 carantină

    chart = charts.stock_by_product(TODAY)

    assert chart.labels[0] == big.lines.get().product.code
    assert [dataset["data"][0] for dataset in chart.datasets] == [10, 2]
    assert chart.rows[0][1] == "10 disponibil, 2 carantină"  # nu „10.000”


# --- Contabilitate --------------------------------------------------------------------------


def test_invoices_by_status(warehouse_user, accounting_user):
    order = sent_order("10")
    receive(order, warehouse_user, "6")
    validated(order, "10")  # blocată: 1.210 lei
    approve_invoice(validated(order, "6"), accounting_user)  # aprobată: 726 lei

    chart = charts.invoices_by_status(TODAY)

    values = dict(zip(chart.labels, chart.datasets[0]["data"], strict=True))
    assert values["Blocată"] == 1210 and values["Aprobată la plată"] == 726
    assert "Total neplătit: 1.936,00 lei" in chart.summary


def test_payments_by_week(warehouse_user, accounting_user):
    order = sent_order("10")
    receive(order, warehouse_user, "10")
    late = approve_invoice(validated(order, "4", invoice_date=day(-40)), accounting_user)
    soon = approve_invoice(validated(order, "6"), accounting_user)
    Invoice.objects.filter(pk=late.pk).update(due_date=day(-1))
    Invoice.objects.filter(pk=soon.pk).update(due_date=TODAY)

    chart = charts.payments_by_week(TODAY)

    data = chart.datasets[0]["data"]
    assert chart.labels[:2] == ["Depășite", "Săptămâna aceasta"]
    assert data[:2] == [float(Decimal("484.00")), float(Decimal("726.00"))]


# --- Cine vede ce ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role_fixture", "expected"),
    [
        ("procurement_user", ["on-time", "late-trend"]),
        ("warehouse_user", ["deliveries", "stock"]),
        ("accounting_user", ["invoices", "payments"]),
        ("admin_user", ["on-time", "late-trend", "deliveries", "stock", "invoices", "payments"]),
    ],
)
def test_charts_per_role(request, role_fixture, expected):
    user = request.getfixturevalue(role_fixture)

    assert [chart.id for chart in charts.charts_for(user, TODAY)] == expected


def test_page_renders_charts_with_safe_data(client, procurement_user, warehouse_user):
    """Datele ajung prin json_script: un nume de furnizor nu poate injecta cod în pagină."""
    supplier = SupplierFactory(name="</script><script>alert(1)</script>")
    order = order_due(-5, "1", supplier=supplier)
    receive_on(order, warehouse_user, -6, "1")
    client.force_login(procurement_user)

    html = client.get(reverse("dashboard:home")).content.decode()

    assert 'data-chart="chart-on-time"' in html
    assert '<script id="chart-on-time" type="application/json">' in html
    assert "</script><script>alert(1)" not in html
    assert "chartjs/chart.umd.js" in html


def test_empty_charts_explain_themselves(client, accounting_user):
    client.force_login(accounting_user)

    html = client.get(reverse("dashboard:home")).content.decode()

    assert "Nicio factură neplătită." in html
    assert "<canvas" not in html  # nimic de desenat


def test_zero_percent_on_time_is_shown_not_hidden(warehouse_user):
    """Un singur furnizor, nicio linie la timp: 0% e informația importantă, nu „lipsă de date”."""
    order = order_due(-5, "4")
    receive_on(order, warehouse_user, -1, "4")

    chart = charts.on_time_by_supplier(TODAY)

    assert chart.datasets[0]["data"] == [0]
    assert not chart.is_empty


def test_no_late_orders_means_an_empty_trend():
    assert charts.late_orders_trend(TODAY).is_empty


def test_summaries_agree_in_number(warehouse_user):
    order_due(-2, "1")

    assert "Azi: 1 comandă întârziată" in charts.late_orders_trend(TODAY).summary
    assert "1 întârziată." in charts.deliveries_ahead(TODAY).summary
