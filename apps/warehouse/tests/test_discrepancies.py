"""Rezolvarea discrepanțelor de către Achiziții: atașare, acceptarea surplusului, retur (I-12)."""

from decimal import Decimal

import pytest

from apps.audit.models import BusinessEvent
from apps.catalog.tests.factories import ProductFactory, SupplierFactory
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.purchasing.services import close_order
from apps.warehouse import services
from apps.warehouse.models import Discrepancy, StockMovement
from apps.warehouse.selectors import available_stock, quarantined_stock

from .scenarios import receive, receive_without_order, sent_order, status

pytestmark = pytest.mark.django_db

D = Decimal
Status = PurchaseOrder.Status


@pytest.fixture
def unordered(warehouse_user):
    """3 bucăți dintr-un produs sosite fără comandă de la un furnizor."""
    supplier = SupplierFactory()
    product = ProductFactory()
    receive_without_order(supplier, warehouse_user, (product, "3"))
    return Discrepancy.objects.get()


# --- Atașare la o linie de comandă ------------------------------------------------------------


def test_attach_to_an_order_line(procurement_user, unordered):
    order = sent_order("5", supplier=unordered.supplier, products=[unordered.product])
    order_line = order.lines.get()

    services.attach_discrepancy(
        unordered, order_line, procurement_user, "Comandă confirmată telefonic"
    )

    unordered.refresh_from_db()
    assert unordered.status == Discrepancy.Status.RESOLVED
    assert unordered.resolution == Discrepancy.Resolution.ATTACHED
    assert unordered.resolved_by == procurement_user
    assert available_stock(unordered.product) == D("3")  # a intrat în stoc
    assert quarantined_stock(unordered.product) == 0
    assert PurchaseOrderLine.objects.with_progress().get(pk=order_line.pk).received_qty == D("3")
    assert status(order) == Status.PARTIALLY_RECEIVED
    event = BusinessEvent.objects.get(event_type=BusinessEvent.Type.DISCREPANCY_ATTACHED)
    assert event.data == {"comandă": order.number, "observații": "Comandă confirmată telefonic"}


def test_attach_candidates(unordered):
    product, supplier = unordered.product, unordered.supplier
    good = sent_order("5", supplier=supplier, products=[product]).lines.get()
    sent_order("2", supplier=supplier, products=[product])  # așteaptă prea puțin
    sent_order("5", products=[product])  # alt furnizor
    sent_order("5", supplier=supplier)  # alt produs

    assert list(services.attach_candidates(unordered)) == [good]


@pytest.mark.parametrize(
    ("make_line", "message"),
    [
        (lambda d: sent_order("5", supplier=d.supplier).lines.get(), "alt produs"),
        (lambda d: sent_order("5", products=[d.product]).lines.get(), "altui furnizor"),
        (
            lambda d: sent_order("2", supplier=d.supplier, products=[d.product]).lines.get(),
            "doar 2",
        ),
    ],
)
def test_attach_rejects_wrong_lines(procurement_user, unordered, make_line, message):
    with pytest.raises(services.WarehouseError, match=message):
        services.attach_discrepancy(unordered, make_line(unordered), procurement_user)
    assert not StockMovement.objects.exists()


def test_cannot_resolve_twice(procurement_user, unordered):
    services.return_discrepancy(unordered, procurement_user, "Nu am comandat")

    with pytest.raises(services.WarehouseError, match="deja rezolvată"):
        services.return_discrepancy(unordered, procurement_user, "Din nou")


# --- Acceptarea surplusului ----------------------------------------------------------------------


def test_accept_over_delivery(procurement_user, warehouse_user):
    """Comandat 10, venit 12: Achizițiile acceptă surplusul → comanda devine 12, stocul 12."""
    order = sent_order("10")
    line = order.lines.get()
    receive(order, warehouse_user, "12")
    surplus = Discrepancy.objects.get()

    services.accept_over_delivery(surplus, procurement_user)

    line.refresh_from_db()
    assert line.quantity == D("12")  # regularizare: cantitatea comandată a crescut
    assert available_stock(line.product) == D("12")
    assert status(order) == Status.RECEIVED
    surplus.refresh_from_db()
    assert "a crescut de la 10 la 12" in surplus.resolution_note


def test_over_delivery_on_closed_order_must_be_returned(procurement_user, warehouse_user):
    order = sent_order("10", "5")
    receive(order, warehouse_user, "12", "0")
    close_order(PurchaseOrder.objects.get(pk=order.pk), "Restul nu mai vine")

    with pytest.raises(services.WarehouseError, match="returnează marfa"):
        services.accept_over_delivery(Discrepancy.objects.get(), procurement_user)


def test_accept_over_delivery_only_for_surplus(procurement_user, unordered):
    with pytest.raises(services.WarehouseError, match="Doar un surplus"):
        services.accept_over_delivery(unordered, procurement_user)


# --- Retur ------------------------------------------------------------------------------------


def test_return_to_supplier(procurement_user, unordered):
    services.return_discrepancy(
        unordered, procurement_user, "Marfă necomandată, returnată cu avizul 12"
    )

    unordered.refresh_from_db()
    assert unordered.resolution == Discrepancy.Resolution.RETURNED
    assert available_stock(unordered.product) == 0  # nu a intrat niciodată în stoc
    assert quarantined_stock(unordered.product) == 0
    assert BusinessEvent.objects.filter(event_type=BusinessEvent.Type.DISCREPANCY_RETURNED).exists()


def test_return_requires_a_reason(procurement_user, unordered):
    with pytest.raises(services.WarehouseError, match="obligatoriu"):
        services.return_discrepancy(unordered, procurement_user, "  ")
