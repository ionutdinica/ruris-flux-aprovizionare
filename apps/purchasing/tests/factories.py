from datetime import timedelta
from decimal import Decimal

import factory
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.catalog.tests.factories import ProductFactory, SupplierFactory
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine


class PurchaseOrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurchaseOrder

    supplier = factory.SubFactory(SupplierFactory)
    owner = factory.SubFactory(UserFactory)
    currency = "RON"
    order_date = factory.LazyFunction(timezone.localdate)
    expected_date = factory.LazyAttribute(lambda o: o.order_date + timedelta(days=14))


class PurchaseOrderLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PurchaseOrderLine

    order = factory.SubFactory(PurchaseOrderFactory)
    product = factory.SubFactory(ProductFactory)
    quantity = Decimal("10")
    unit_price = Decimal("100.00")
    expected_date = factory.LazyAttribute(lambda line: line.order.expected_date)
