"""Registrul de stoc: ieșiri, ajustări, retururi pe comandă, imposibilitatea modificării."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory
from apps.core.models import ImmutableRecordError
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.warehouse import services
from apps.warehouse.models import StockMovement
from apps.warehouse.selectors import available_stock

from .scenarios import receive, sent_order, status

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def stocked(warehouse_user):
    """Un produs cu 10 bucăți în stoc, recepționate pe o comandă."""
    order = sent_order("10")
    receive(order, warehouse_user, "10")
    return order.lines.get()


def move(line_or_product, kind, quantity, user, **kwargs):
    product = getattr(line_or_product, "product", line_or_product)
    return services.record_stock_movement(
        product, kind, D(quantity), user, "motiv de test", **kwargs
    )


def test_consumption_and_adjustments(warehouse_user, stocked):
    move(stocked, "CONSUMPTION", "4", warehouse_user)
    move(stocked, "ADJUSTMENT_MINUS", "1", warehouse_user)
    move(stocked, "ADJUSTMENT_PLUS", "2", warehouse_user)

    assert available_stock(stocked.product) == D("7")  # 10 − 4 − 1 + 2


def test_stock_cannot_become_negative(warehouse_user, stocked):
    with pytest.raises(services.WarehouseError, match="disponibil 10"):
        move(stocked, "CONSUMPTION", "11", warehouse_user)
    assert available_stock(stocked.product) == D("10")


def test_movement_requires_reason_and_positive_quantity(warehouse_user, stocked):
    with pytest.raises(services.WarehouseError, match="obligatoriu"):
        services.record_stock_movement(stocked.product, "CONSUMPTION", D("1"), warehouse_user, "")
    with pytest.raises(services.WarehouseError, match="pozitivă"):
        move(stocked, "CONSUMPTION", "0", warehouse_user)


def test_movement_date_cannot_be_in_the_future(warehouse_user, stocked):
    with pytest.raises(services.WarehouseError, match="viitor"):
        move(
            stocked,
            "CONSUMPTION",
            "1",
            warehouse_user,
            date=timezone.localdate() + timedelta(days=1),
        )


def test_supplier_return_on_order_line_reopens_the_order(warehouse_user, stocked):
    """Marfă defectă returnată: comanda redevine parțial recepționată (I-15)."""
    assert status(stocked.order) == PurchaseOrder.Status.RECEIVED

    move(stocked, "SUPPLIER_RETURN", "3", warehouse_user, order_line=stocked)

    assert available_stock(stocked.product) == D("7")
    assert PurchaseOrderLine.objects.with_progress().get(pk=stocked.pk).received_qty == D("7")
    assert status(stocked.order) == PurchaseOrder.Status.PARTIALLY_RECEIVED


def test_cannot_return_more_than_received_on_the_line(warehouse_user, stocked):
    move(stocked, "ADJUSTMENT_PLUS", "5", warehouse_user)  # 15 în stoc, 10 recepționate pe linie

    with pytest.raises(services.WarehouseError, match="doar 10"):
        move(stocked, "SUPPLIER_RETURN", "12", warehouse_user, order_line=stocked)


def test_only_returns_can_be_linked_to_an_order_line(warehouse_user, stocked):
    with pytest.raises(services.WarehouseError, match="Doar un retur"):
        move(stocked, "CONSUMPTION", "1", warehouse_user, order_line=stocked)


def test_ledger_cannot_be_modified_or_deleted(warehouse_user, stocked):
    movement = StockMovement.objects.first()

    movement.quantity = D("1000")
    with pytest.raises(ImmutableRecordError):
        movement.save()
    with pytest.raises(ImmutableRecordError):
        movement.delete()
    with pytest.raises(ImmutableRecordError):
        StockMovement.objects.update(quantity=D("1000"))


def test_database_enforces_the_sign_of_each_movement_type():
    """Chiar ocolind regulile din aplicație, baza de date refuză o ieșire cu semn plus."""
    with pytest.raises(IntegrityError):
        StockMovement.objects.create(
            product=ProductFactory(), type=StockMovement.Type.CONSUMPTION, quantity=D("5")
        )


def test_movements_record_who_made_them(warehouse_user, stocked):
    movement = move(stocked, "CONSUMPTION", "1", warehouse_user)

    assert movement.created_by == warehouse_user
    assert movement.quantity == D("-1")
