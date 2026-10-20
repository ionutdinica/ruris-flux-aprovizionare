from decimal import Decimal

import factory

from apps.catalog.tests.factories import ProductFactory, SupplierFactory
from apps.warehouse.models import GoodsReceipt, GoodsReceiptLine


class GoodsReceiptFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = GoodsReceipt

    supplier = factory.SubFactory(SupplierFactory)


class GoodsReceiptLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = GoodsReceiptLine

    receipt = factory.SubFactory(GoodsReceiptFactory)
    product = factory.SubFactory(ProductFactory)
    quantity_received = Decimal("10")
