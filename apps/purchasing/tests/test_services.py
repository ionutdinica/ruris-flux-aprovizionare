"""Tranzițiile de status ale comenzii (docs/03-fluxuri-si-stari.md)."""

from decimal import Decimal
from unittest import mock

import pytest

from apps.audit.models import BusinessEvent
from apps.purchasing import services
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services import TransitionError

from .factories import PurchaseOrderFactory, PurchaseOrderLineFactory

pytestmark = pytest.mark.django_db

Status = PurchaseOrder.Status
T = BusinessEvent.Type


@pytest.fixture
def draft():
    order = PurchaseOrderFactory()
    PurchaseOrderLineFactory(order=order)
    return order


def set_status(order, status):
    PurchaseOrder.objects.filter(pk=order.pk).update(status=status)
    order.refresh_from_db()


def fake_received(order, quantities):
    """Simulează cantitățile recepționate pe liniile comenzii, în ordine.
    (Recepțiile reale apar în capitolul 5; acolo se testează și fluxul complet.)"""
    line_ids = order.lines.order_by("id").values_list("id", flat=True)
    received = {pk: Decimal(qty) for pk, qty in zip(line_ids, quantities, strict=True)}
    return mock.patch("apps.purchasing.services.received_quantities", return_value=received)


# --- Trimitere ------------------------------------------------------------------------------


def test_send_order(draft):
    services.send_order(draft)

    draft.refresh_from_db()
    assert draft.status == Status.SENT
    assert draft.sent_at is not None
    event = BusinessEvent.objects.get(event_type=T.ORDER_SENT)
    assert event.target == draft


def test_cannot_send_empty_order():
    order = PurchaseOrderFactory()

    with pytest.raises(TransitionError, match="nicio linie"):
        services.send_order(order)


def test_cannot_send_twice(draft):
    services.send_order(draft)

    with pytest.raises(TransitionError):
        services.send_order(draft)


def test_cannot_send_with_inactive_supplier(draft):
    draft.supplier.is_active = False
    draft.supplier.save()

    with pytest.raises(TransitionError, match="inactiv"):
        services.send_order(draft)


def test_cannot_send_with_inactive_product(draft):
    product = draft.lines.get().product
    product.is_active = False
    product.save()

    with pytest.raises(TransitionError, match=product.code):
        services.send_order(draft)


# --- Anulare ---------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [Status.DRAFT, Status.SENT])
def test_cancel_order(draft, status):
    set_status(draft, status)

    services.cancel_order(draft, "Furnizorul nu mai are stoc")

    draft.refresh_from_db()
    assert draft.status == Status.CANCELLED
    assert draft.close_reason == "Furnizorul nu mai are stoc"
    assert BusinessEvent.objects.get(event_type=T.ORDER_CANCELLED).data == {
        "motiv": "Furnizorul nu mai are stoc"
    }


def test_cancel_requires_reason(draft):
    with pytest.raises(TransitionError, match="obligatoriu"):
        services.cancel_order(draft, "   ")


def test_cannot_cancel_after_goods_were_received(draft):
    set_status(draft, Status.SENT)

    with fake_received(draft, ["3"]), pytest.raises(TransitionError, match="Închide cu rest"):
        services.cancel_order(draft, "motiv")


# --- Închidere cu rest -------------------------------------------------------------------------


def test_close_partially_received_order(draft):
    set_status(draft, Status.PARTIALLY_RECEIVED)

    services.close_order(draft, "Restul nu mai e necesar")

    draft.refresh_from_db()
    assert draft.status == Status.CLOSED


@pytest.mark.parametrize("status", [Status.DRAFT, Status.SENT, Status.RECEIVED, Status.CANCELLED])
def test_close_only_from_partially_received(draft, status):
    set_status(draft, status)

    with pytest.raises(TransitionError):
        services.close_order(draft, "motiv")


# --- Statusul automat din recepții ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("received", "expected"),
    [
        (["0", "0"], Status.SENT),
        (["4", "0"], Status.PARTIALLY_RECEIVED),
        (["10", "4"], Status.PARTIALLY_RECEIVED),
        (["10", "5"], Status.RECEIVED),
        (["12", "5"], Status.RECEIVED),  # surplusul nu schimbă nimic
    ],
)
def test_refresh_status(received, expected):
    order = PurchaseOrderFactory()
    PurchaseOrderLineFactory(order=order, quantity=Decimal("10"))
    PurchaseOrderLineFactory(order=order, quantity=Decimal("5"))
    set_status(order, Status.SENT)

    with fake_received(order, received):
        services.refresh_status(order)

    order.refresh_from_db()
    assert order.status == expected


@pytest.mark.parametrize("status", [Status.DRAFT, Status.CLOSED, Status.CANCELLED])
def test_refresh_status_ignores_final_and_draft_orders(draft, status):
    set_status(draft, status)

    with fake_received(draft, ["10"]):
        services.refresh_status(draft)

    draft.refresh_from_db()
    assert draft.status == status
