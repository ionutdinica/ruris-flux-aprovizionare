"""Detectorul de probleme: fiecare regulă din docs/05-reguli-business.md, §4, și cine o primește."""

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.tests.factories import UserFactory
from apps.catalog.tests.factories import ProductFactory, SupplierFactory
from apps.invoicing.models import Invoice
from apps.invoicing.services import approve_invoice, mark_paid
from apps.invoicing.tests.scenarios import validated
from apps.notifications.alerts import Section, alerts_for, collect
from apps.purchasing import services as purchasing
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.warehouse.tests.scenarios import receive, receive_without_order, sent_order

pytestmark = pytest.mark.django_db

D = Decimal
TODAY = timezone.localdate()


def days(n):
    return TODAY + datetime.timedelta(days=n)


def codes(user):
    return [alert.code for alert in alerts_for(user)]


def order_for(owner, *quantities, expected=None):
    """Comandă trimisă, cu responsabil și termen dat (în trecut = întârziată)."""
    order = sent_order(*quantities)
    PurchaseOrder.objects.filter(pk=order.pk).update(owner=owner)
    if expected is not None:
        PurchaseOrderLine.objects.filter(order=order).update(expected_date=expected)
    return PurchaseOrder.objects.get(pk=order.pk)


def set_status_since(invoice, when):
    Invoice.objects.filter(pk=invoice.pk).update(status_changed_at=when)


def business_days_ago(count):
    """Un moment de acum `count` zile lucrătoare (sare peste weekend)."""
    day = TODAY
    while count:
        day -= datetime.timedelta(days=1)
        if day.weekday() < 5:
            count -= 1
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(10)))


@pytest.fixture
def other_buyer(db):
    return UserFactory(role=User.Role.PROCUREMENT)


# --- Comenzi întârziate și livrări de azi -------------------------------------------------------


def test_late_order_goes_to_its_owner_and_the_warehouse(
    procurement_user, other_buyer, warehouse_user, accounting_user, admin_user
):
    order = order_for(procurement_user, "10", expected=days(-3))
    receive(order, warehouse_user, "6")

    [alert] = alerts_for(procurement_user)

    assert alert.code == "ORDER_LATE" and alert.section == Section.LATE
    assert "Nesosit: 4 buc" in alert.detail and "(3 zile întârziere)" in alert.detail
    assert alert.url == order.get_absolute_url()
    assert codes(warehouse_user) == ["ORDER_LATE"]
    assert codes(other_buyer) == codes(accounting_user) == codes(admin_user) == []


def test_fully_received_or_closed_orders_are_not_late(procurement_user, warehouse_user):
    received = order_for(procurement_user, "5", expected=days(-2))
    receive(received, warehouse_user, "5")
    closed = order_for(procurement_user, "5", expected=days(-2))
    receive(closed, warehouse_user, "1")
    purchasing.close_order(closed, "Restul nu mai vine")
    order_for(procurement_user, "5", expected=days(1))  # termenul nu a venit

    assert alerts_for(procurement_user) == []


def test_delivery_expected_today_only_for_the_warehouse(procurement_user, warehouse_user):
    order_for(procurement_user, "8", expected=TODAY)

    assert codes(warehouse_user) == ["DELIVERY_EXPECTED_TODAY"]
    assert codes(procurement_user) == []
    assert "Se așteaptă azi: 8 buc" in alerts_for(warehouse_user)[0].detail


def test_several_late_lines_make_one_alert_per_order(procurement_user):
    order_for(procurement_user, "10", "3", expected=days(-1))

    [alert] = alerts_for(procurement_user)

    assert alert.detail.count("termen") == 2


# --- Carantină ----------------------------------------------------------------------------------


def test_discrepancy_goes_to_the_order_owner(procurement_user, other_buyer, warehouse_user):
    order = order_for(procurement_user, "10")
    receive(order, warehouse_user, "12")  # 2 peste comandă

    assert codes(procurement_user) == ["DISCREPANCY_OPEN"]
    assert codes(other_buyer) == []
    assert "2 buc de la" in alerts_for(procurement_user)[0].detail


def test_goods_without_order_go_to_all_procurement(procurement_user, other_buyer, warehouse_user):
    receive_without_order(SupplierFactory(), warehouse_user, (ProductFactory(), "3"))

    assert codes(procurement_user) == codes(other_buyer) == ["DISCREPANCY_OPEN"]
    assert codes(warehouse_user) == []


# --- Facturi --------------------------------------------------------------------------------


def test_blocked_invoice_goes_to_accounting_and_the_order_owner(
    procurement_user, other_buyer, warehouse_user, accounting_user
):
    order = order_for(procurement_user, "10")
    receive(order, warehouse_user, "6")
    validated(order, "10")

    [alert] = alerts_for(accounting_user)

    assert alert.code == "INVOICE_BLOCKED" and "4 buc nesosite" in alert.detail
    assert "INVOICE_BLOCKED" in codes(procurement_user)
    assert codes(other_buyer) == [] and "INVOICE_BLOCKED" not in codes(warehouse_user)


@pytest.mark.parametrize(("waiting", "expected"), [(1, []), (2, ["INVOICE_RATE_PENDING"])])
def test_rate_pending_only_after_one_business_day(accounting_user, waiting, expected):
    order = order_for(accounting_user, "1")
    order.currency = "EUR"
    order.save()
    invoice = validated(order, "1")  # niciun curs EUR salvat → în așteptare
    assert invoice.status == Invoice.Status.RATE_PENDING
    set_status_since(invoice, business_days_ago(waiting))

    assert codes(accounting_user) == expected


@pytest.mark.parametrize(("waiting", "expected"), [(3, []), (4, ["INVOICE_MATCHED_WAITING"])])
def test_matched_but_not_approved(accounting_user, warehouse_user, waiting, expected):
    order = order_for(accounting_user, "5")
    receive(order, warehouse_user, "5")
    invoice = validated(order, "5")
    set_status_since(invoice, business_days_ago(waiting))

    assert codes(accounting_user) == expected


@pytest.mark.parametrize(
    ("due_in", "expected"),
    [(-2, ["INVOICE_OVERDUE"]), (0, ["INVOICE_DUE_SOON"]), (3, ["INVOICE_DUE_SOON"]), (4, [])],
)
def test_approved_invoice_due_dates(accounting_user, warehouse_user, due_in, expected):
    order = order_for(accounting_user, "5")
    receive(order, warehouse_user, "5")
    # Emisă acum 30 de zile: baza de date nu permite scadența înaintea datei facturii.
    invoice = approve_invoice(validated(order, "5", invoice_date=days(-30)), accounting_user)
    Invoice.objects.filter(pk=invoice.pk).update(due_date=days(due_in))

    assert codes(accounting_user) == expected


def test_paid_invoice_is_no_longer_reported(accounting_user, warehouse_user):
    order = order_for(accounting_user, "5")
    receive(order, warehouse_user, "5")
    invoice = approve_invoice(validated(order, "5", invoice_date=days(-30)), accounting_user)
    Invoice.objects.filter(pk=invoice.pk).update(due_date=days(-1))
    mark_paid(Invoice.objects.get(pk=invoice.pk), TODAY)

    assert codes(accounting_user) == []


# --- General ------------------------------------------------------------------------------------


def test_inactive_user_gets_nothing(procurement_user):
    order_for(procurement_user, "10", expected=days(-3))
    procurement_user.is_active = False

    assert alerts_for(procurement_user) == []


def test_sections_are_ordered_late_blocked_today(warehouse_user, procurement_user):
    order_for(procurement_user, "1", expected=TODAY)
    order_for(procurement_user, "1", expected=days(-1))

    sections = [alert.section for alert in alerts_for(warehouse_user)]

    assert sections == [Section.LATE, Section.TODAY]


def test_keys_are_stable_from_one_day_to_the_next(procurement_user):
    """Cheia nu depinde de zi: o problemă veche nu apare „NOU” în fiecare dimineață."""
    order_for(procurement_user, "10", expected=days(-5))

    first = [a.key for a in collect(TODAY)]
    second = [a.key for a in collect(days(1))]

    assert first == second
