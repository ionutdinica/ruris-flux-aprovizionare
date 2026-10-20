"""Confirmarea recepțiilor: tranșe, surplus, marfă necomandată, statusul comenzii."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from apps.audit.models import BusinessEvent
from apps.catalog.tests.factories import ProductFactory
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.purchasing.services import cancel_order
from apps.warehouse import services
from apps.warehouse.models import Discrepancy, GoodsReceipt, GoodsReceiptLine, StockMovement
from apps.warehouse.selectors import available_stock, products_with_stock, quarantined_stock

from .scenarios import receive, receive_without_order, sent_order, status

pytestmark = pytest.mark.django_db

Status = PurchaseOrder.Status
D = Decimal


def received(line):
    return PurchaseOrderLine.objects.with_progress().get(pk=line.pk).received_qty


# --- Livrare completă, în tranșe, surplus -----------------------------------------------------


def test_full_delivery(warehouse_user):
    order = sent_order("10")
    line = order.lines.get()

    receipt = receive(order, warehouse_user, "10")

    assert receipt.status == GoodsReceipt.Status.CONFIRMED
    assert receipt.number.startswith("REC-")
    assert receipt.confirmed_by == warehouse_user
    assert received(line) == D("10")
    assert available_stock(line.product) == D("10")
    assert status(order) == Status.RECEIVED
    assert not Discrepancy.objects.exists()


def test_delivery_in_two_tranches(warehouse_user):
    order = sent_order("10", "5")
    first, second = order.lines.order_by("id")

    receive(order, warehouse_user, "4", "0")
    assert status(order) == Status.PARTIALLY_RECEIVED
    assert received(first) == D("4")

    receive(order, warehouse_user, "6", "5")
    assert status(order) == Status.RECEIVED
    assert received(first) == D("10") and received(second) == D("5")


def test_over_delivery_goes_to_quarantine(warehouse_user):
    """Comandat 10, venit 12: 10 intră în stoc, 2 în carantină (I-11)."""
    order = sent_order("10")
    line = order.lines.get()

    receipt = receive(order, warehouse_user, "12")

    receipt_line = receipt.lines.get()
    assert (receipt_line.quantity_accepted, receipt_line.quantity_quarantined) == (D("10"), D("2"))
    assert available_stock(line.product) == D("10")  # carantina NU e stoc disponibil
    assert quarantined_stock(line.product) == D("2")
    discrepancy = Discrepancy.objects.get()
    assert (discrepancy.type, discrepancy.quantity) == (Discrepancy.Type.OVER_DELIVERY, D("2"))
    assert status(order) == Status.RECEIVED


def test_surplus_over_previous_tranche(warehouse_user):
    """A doua tranșă ține cont de ce s-a acceptat deja: comandat 10, venit 7 + 5."""
    order = sent_order("10")

    receive(order, warehouse_user, "7")
    receipt = receive(order, warehouse_user, "5")

    line = receipt.lines.get()
    assert (line.quantity_accepted, line.quantity_quarantined) == (D("3"), D("2"))


def test_unordered_product_on_an_order_receipt(warehouse_user):
    order = sent_order("10")
    unexpected = ProductFactory()

    receive(order, warehouse_user, "10", extra=[(unexpected, "3")])

    discrepancy = Discrepancy.objects.get()
    assert discrepancy.type == Discrepancy.Type.UNORDERED
    assert available_stock(unexpected) == 0
    assert quarantined_stock(unexpected) == D("3")


def test_goods_without_any_order(warehouse_user):
    product = ProductFactory()
    supplier = sent_order("1").supplier

    receipt = receive_without_order(supplier, warehouse_user, (product, "8"))

    assert receipt.purchase_order is None
    assert Discrepancy.objects.get().quantity == D("8")
    assert available_stock(product) == 0


def test_lines_not_delivered_are_ignored(warehouse_user):
    order = sent_order("10", "5")

    receive(order, warehouse_user, "10", "0")

    assert StockMovement.objects.count() == 1
    assert status(order) == Status.PARTIALLY_RECEIVED


# --- Reguli și protecții -------------------------------------------------------------------------


def test_receipt_number_is_given_on_confirmation(warehouse_user):
    order = sent_order("10")

    draft = receive(order, warehouse_user, "10", confirm=False)
    assert draft.number is None and str(draft).startswith("Recepție nouă")

    services.confirm_receipt(draft, warehouse_user)
    draft.refresh_from_db()
    assert draft.number == f"REC-{timezone.localdate().year}-0001"


def test_confirm_twice_is_rejected(warehouse_user):
    receipt = receive(sent_order("10"), warehouse_user, "10")

    with pytest.raises(services.WarehouseError, match="deja confirmată"):
        services.confirm_receipt(receipt, warehouse_user)
    assert StockMovement.objects.count() == 1


def test_receipt_with_nothing_counted_is_rejected(warehouse_user):
    receipt = receive(sent_order("10"), warehouse_user, "0", confirm=False)

    with pytest.raises(services.WarehouseError, match="nicio cantitate"):
        services.confirm_receipt(receipt, warehouse_user)


def test_cannot_receive_on_a_cancelled_order(warehouse_user):
    order = sent_order("10")
    receipt = receive(order, warehouse_user, "10", confirm=False)
    cancel_order(order, "Furnizorul a anulat")

    with pytest.raises(services.WarehouseError, match="nu se mai poate recepționa"):
        services.confirm_receipt(receipt, warehouse_user)


def test_receipt_validation():
    order = sent_order("10")
    other_order = sent_order("5")
    future = GoodsReceipt(
        supplier=order.supplier, receipt_date=timezone.localdate() + timedelta(days=1)
    )
    wrong_supplier = GoodsReceipt(supplier=other_order.supplier, purchase_order=order)

    with pytest.raises(ValidationError, match="viitor"):
        future.full_clean()
    with pytest.raises(ValidationError, match="altui furnizor"):
        wrong_supplier.full_clean()


def test_receipt_line_must_match_the_order_line():
    order = sent_order("10")
    receipt = GoodsReceipt.objects.create(supplier=order.supplier, purchase_order=order)
    line = GoodsReceiptLine(
        receipt=receipt, product=ProductFactory(), order_line=order.lines.get(), quantity_received=1
    )

    with pytest.raises(ValidationError, match="Produsul diferă"):
        line.full_clean()


def test_same_order_line_only_once_per_receipt():
    order = sent_order("10")
    order_line = order.lines.get()
    receipt = GoodsReceipt.objects.create(supplier=order.supplier, purchase_order=order)
    GoodsReceiptLine.objects.create(
        receipt=receipt, product=order_line.product, order_line=order_line, quantity_received=1
    )

    with pytest.raises(IntegrityError):
        GoodsReceiptLine.objects.create(
            receipt=receipt, product=order_line.product, order_line=order_line, quantity_received=1
        )


def test_draft_can_be_deleted_confirmed_cannot(warehouse_user):
    order = sent_order("10")
    draft = receive(order, warehouse_user, "10", confirm=False)
    services.delete_draft_receipt(draft)
    assert not GoodsReceipt.objects.exists()

    confirmed = receive(order, warehouse_user, "10")
    with pytest.raises(services.WarehouseError):
        services.delete_draft_receipt(confirmed)


# --- Efecte asupra comenzilor -----------------------------------------------------------------


def test_cancel_is_impossible_after_a_real_receipt(warehouse_user):
    order = sent_order("10")
    receive(order, warehouse_user, "3")

    with pytest.raises(ValidationError, match="Închide cu rest"):
        cancel_order(order, "motiv")


def test_late_orders_use_real_receipts(warehouse_user):
    today = timezone.localdate()
    order = sent_order("10")
    PurchaseOrderLine.objects.filter(order=order).update(expected_date=today - timedelta(days=1))

    assert PurchaseOrder.objects.late().filter(pk=order.pk).exists()
    receive(order, warehouse_user, "6")
    assert PurchaseOrder.objects.late().filter(pk=order.pk).exists()  # încă lipsesc 4
    receive(order, warehouse_user, "4")
    assert not PurchaseOrder.objects.late().filter(pk=order.pk).exists()


def test_confirmation_is_recorded(warehouse_user):
    receipt = receive(sent_order("10"), warehouse_user, "12")

    event = BusinessEvent.objects.get(event_type=BusinessEvent.Type.RECEIPT_CONFIRMED)
    assert event.target == receipt
    assert event.actor == warehouse_user
    assert "1 linii au mers în carantină" in event.message


def test_products_with_stock(warehouse_user):
    order = sent_order("10")
    product = order.lines.get().product
    receive(order, warehouse_user, "13")

    annotated = products_with_stock().get(pk=product.pk)

    assert (annotated.stock_available, annotated.stock_quarantined) == (D("10"), D("3"))
