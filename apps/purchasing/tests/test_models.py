"""Modelul comenzii: numerotare, valori, validări, întârzieri, istoric."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from auditlog.context import set_actor
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.timeline import history_for
from apps.catalog.tests.factories import ProductFactory, SupplierFactory
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, money

from .factories import PurchaseOrderFactory, PurchaseOrderLineFactory

pytestmark = pytest.mark.django_db

Status = PurchaseOrder.Status
TODAY = timezone.localdate()


# --- Numerotare ------------------------------------------------------------------------


def test_numbers_are_consecutive_per_year():
    first = PurchaseOrderFactory(order_date=date(2026, 3, 1))
    second = PurchaseOrderFactory(order_date=date(2026, 3, 2))
    next_year = PurchaseOrderFactory(order_date=date(2027, 1, 5))

    assert first.number == "CMD-2026-0001"
    assert second.number == "CMD-2026-0002"
    assert next_year.number == "CMD-2027-0001"  # numerotarea reîncepe în fiecare an


def test_number_does_not_change_on_save():
    order = PurchaseOrderFactory()
    number = order.number

    order.notes = "modificare"
    order.save()

    assert order.number == number


# --- Valori ------------------------------------------------------------------------------


def test_money_rounds_half_up():
    assert money(Decimal("0.005")) == Decimal("0.01")
    assert money(Decimal("2.675")) == Decimal("2.68")  # float ar da 2.67


def test_line_and_order_amounts():
    order = PurchaseOrderFactory()
    PurchaseOrderLineFactory(order=order, quantity=Decimal("3"), unit_price=Decimal("33.3333"))
    PurchaseOrderLineFactory(
        order=order, quantity=Decimal("2"), unit_price=Decimal("10"), vat_rate=Decimal("11.00")
    )

    # 3 × 33,3333 = 99,9999 → 100,00 (rotunjit pe linie); TVA 21% = 21,00
    # 2 × 10 = 20,00; TVA 11% = 2,20
    assert order.net_amount == Decimal("120.00")
    assert order.vat_amount == Decimal("23.20")
    assert order.gross_amount == Decimal("143.20")


def test_with_totals_matches_python_totals():
    order = PurchaseOrderFactory()
    PurchaseOrderLineFactory(order=order, quantity=Decimal("3"), unit_price=Decimal("33.3333"))
    PurchaseOrderLineFactory(order=order, quantity=Decimal("2"), unit_price=Decimal("10"))

    annotated = PurchaseOrder.objects.with_totals().get(pk=order.pk)

    assert annotated.net_total == order.net_amount == Decimal("120.00")


# --- Validări ----------------------------------------------------------------------------


def test_expected_date_cannot_be_before_order_date():
    order = PurchaseOrderFactory.build(
        supplier=SupplierFactory(), order_date=TODAY, expected_date=TODAY - timedelta(days=1)
    )

    with pytest.raises(ValidationError) as error:
        order.clean()

    assert "expected_date" in error.value.message_dict


def test_inactive_supplier_cannot_be_used_on_new_orders():
    order = PurchaseOrderFactory.build(supplier=SupplierFactory(is_active=False))

    with pytest.raises(ValidationError) as error:
        order.clean()

    assert "supplier" in error.value.message_dict


def test_inactive_product_cannot_be_added():
    line = PurchaseOrderLineFactory.build(
        order=PurchaseOrderFactory(), product=ProductFactory(is_active=False)
    )

    with pytest.raises(ValidationError) as error:
        line.clean()

    assert "product" in error.value.message_dict


def test_database_rejects_non_positive_quantity():
    """Pe lângă validarea din formular, baza de date însăși refuză valorile imposibile."""
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        PurchaseOrderLineFactory(quantity=Decimal("0"))


# --- Modificări după trimitere (I-07) -----------------------------------------------------


@pytest.fixture
def sent_line():
    line = PurchaseOrderLineFactory(quantity=Decimal("10"), unit_price=Decimal("5"))
    PurchaseOrder.objects.filter(pk=line.order_id).update(status=Status.SENT)
    return PurchaseOrderLine.objects.select_related("order").get(pk=line.pk)


def test_sent_line_allows_later_date_and_more_quantity(sent_line):
    sent_line.expected_date += timedelta(days=7)
    sent_line.quantity = Decimal("15")

    sent_line.clean()  # nu ridică eroare


@pytest.mark.parametrize(
    ("field", "value"),
    [("quantity", Decimal("8")), ("unit_price", Decimal("4.5")), ("vat_rate", Decimal("11.00"))],
)
def test_sent_line_rejects_locked_changes(sent_line, field, value):
    setattr(sent_line, field, value)

    with pytest.raises(ValidationError) as error:
        sent_line.clean()

    assert field in error.value.message_dict


def test_sent_line_rejects_product_change(sent_line):
    sent_line.product = ProductFactory()

    with pytest.raises(ValidationError) as error:
        sent_line.clean()

    assert "product" in error.value.message_dict


# --- Întârzieri ----------------------------------------------------------------------------


def make_order(status, expected):
    order = PurchaseOrderFactory(order_date=expected - timedelta(days=30), expected_date=expected)
    PurchaseOrderLineFactory(order=order)
    PurchaseOrder.objects.filter(pk=order.pk).update(status=status)
    return order


def test_late_orders():
    late = make_order(Status.SENT, TODAY - timedelta(days=1))
    make_order(Status.SENT, TODAY)  # termen azi: încă nu e întârziată
    make_order(Status.DRAFT, TODAY - timedelta(days=5))  # ciornă: nu se așteaptă nimic
    make_order(Status.CANCELLED, TODAY - timedelta(days=5))

    assert list(PurchaseOrder.objects.late()) == [late]


# --- Istoric ----------------------------------------------------------------------------------


def test_order_history_includes_line_changes(procurement_user):
    with set_actor(procurement_user):
        order = PurchaseOrderFactory()
        line = PurchaseOrderLineFactory(order=order, quantity=Decimal("10"))
        line.quantity = Decimal("12")
        line.save()

    titles = [entry.title for entry in history_for(order)]

    assert any("Linie de comandă" in t for t in titles)  # modificarea liniei apare la comandă
    assert any(t.startswith("Comandă «") for t in titles)
