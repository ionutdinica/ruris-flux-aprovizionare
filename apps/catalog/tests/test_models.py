from decimal import Decimal

import pytest
from auditlog.context import set_actor
from auditlog.models import LogEntry
from django.core.exceptions import ValidationError

from apps.catalog.models import Product, Supplier

from .factories import ProductFactory, SupplierFactory

pytestmark = pytest.mark.django_db


# --- Furnizori ----------------------------------------------------------------------


def test_romanian_cui_is_validated():
    supplier = Supplier(name="Test", country="RO", tax_id="14399841")  # cifră de control greșită

    with pytest.raises(ValidationError) as error:
        supplier.full_clean()

    assert "tax_id" in error.value.message_dict


def test_romanian_cui_is_stored_without_ro_prefix():
    supplier = Supplier(name="Test", country="RO", tax_id="ro 14399840")

    supplier.full_clean()

    assert supplier.tax_id == "14399840"


def test_same_cui_with_and_without_prefix_is_a_duplicate():
    """„RO14399840” și „14399840” sunt aceeași firmă: nu poate fi adăugată de două ori."""
    SupplierFactory(tax_id="14399840")
    duplicate = Supplier(name="Altă denumire", country="RO", tax_id="RO14399840")

    with pytest.raises(ValidationError) as error:
        duplicate.full_clean()

    assert "tax_id" in error.value.message_dict


def test_foreign_tax_id_is_not_validated_as_cui():
    supplier = Supplier(name="Lieferant GmbH", country="de", tax_id="de 811 907 980")

    supplier.full_clean()

    assert supplier.country == "DE"
    assert supplier.tax_id == "DE811907980"


def test_active_filter():
    active = SupplierFactory()
    SupplierFactory(is_active=False)

    assert list(Supplier.objects.active()) == [active]


def test_supplier_changes_are_audited(procurement_user):
    supplier = SupplierFactory(email="vechi@furnizor.test")

    with set_actor(procurement_user):
        supplier.email = "nou@furnizor.test"
        supplier.save()

    entry = LogEntry.objects.get_for_object(supplier).first()  # cea mai recentă
    assert entry.actor == procurement_user
    assert entry.changes_dict == {"email": ["vechi@furnizor.test", "nou@furnizor.test"]}
    # „modificat la” se schimbă la fiecare salvare, dar nu apare în jurnal (zgomot)


# --- Produse -------------------------------------------------------------------------


def test_product_defaults_to_standard_vat():
    product = ProductFactory()

    assert product.vat_rate == Decimal("21.00")


def test_product_code_is_normalized():
    product = Product(code="  p-001 ", name="Șurub", unit=Product.Unit.PIECE)

    product.full_clean()

    assert product.code == "P-001"


def test_only_romanian_vat_rates_are_accepted():
    product = Product(code="X", name="X", unit=Product.Unit.PIECE, vat_rate=Decimal("19.00"))

    with pytest.raises(ValidationError) as error:
        product.full_clean()

    assert "vat_rate" in error.value.message_dict


def test_str():
    assert str(ProductFactory(code="P-1", name="Motor")) == "P-1 – Motor"
