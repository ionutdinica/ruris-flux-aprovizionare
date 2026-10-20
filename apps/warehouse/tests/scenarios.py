"""Scenarii de test realiste, construite prin aceleași servicii pe care le folosește aplicația."""

from decimal import Decimal

from apps.catalog.tests.factories import ProductFactory, SupplierFactory
from apps.purchasing import services as purchasing
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.tests.factories import PurchaseOrderFactory, PurchaseOrderLineFactory
from apps.warehouse import services
from apps.warehouse.models import GoodsReceipt, GoodsReceiptLine


def sent_order(*quantities, supplier=None, products=None):
    """O comandă trimisă furnizorului, cu câte o linie pentru fiecare cantitate."""
    supplier = supplier or SupplierFactory()
    order = PurchaseOrderFactory(supplier=supplier)
    for index, quantity in enumerate(quantities):
        product = products[index] if products else ProductFactory()
        PurchaseOrderLineFactory(order=order, product=product, quantity=Decimal(quantity))
    return purchasing.send_order(order)


def receive(order, user, *counted, extra=(), confirm=True):
    """Depozitul numără marfa pe comandă: `counted` = cantitățile pe liniile comenzii, în
    ordine; `extra` = [(produs, cantitate)] pentru produse care nu sunt pe comandă."""
    receipt = GoodsReceipt.objects.create(supplier=order.supplier, purchase_order=order)
    for line, quantity in zip(order.lines.order_by("id"), counted, strict=False):
        GoodsReceiptLine.objects.create(
            receipt=receipt,
            product=line.product,
            order_line=line,
            quantity_received=Decimal(quantity),
        )
    for product, quantity in extra:
        GoodsReceiptLine.objects.create(
            receipt=receipt, product=product, quantity_received=Decimal(quantity)
        )
    if confirm:
        services.confirm_receipt(receipt, user)
        receipt.refresh_from_db()
    return receipt


def receive_without_order(supplier, user, *items):
    """Marfă sosită fără comandă: items = [(produs, cantitate)]."""
    receipt = GoodsReceipt.objects.create(supplier=supplier)
    for product, quantity in items:
        GoodsReceiptLine.objects.create(
            receipt=receipt, product=product, quantity_received=Decimal(quantity)
        )
    services.confirm_receipt(receipt, user)
    receipt.refresh_from_db()
    return receipt


def status(order):
    return PurchaseOrder.objects.get(pk=order.pk).status
