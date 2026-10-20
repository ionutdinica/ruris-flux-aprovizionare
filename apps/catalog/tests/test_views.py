"""Paginile nomenclatoarelor: listă, căutare, detaliu, adăugare, editare.

Accesul pe roluri (403) e verificat automat pentru toate paginile în
apps/accounts/tests/test_url_permissions.py.
"""

import pytest
from auditlog.models import LogEntry
from django.urls import reverse

from apps.catalog.models import Product, Supplier

from .factories import ProductFactory, SupplierFactory

pytestmark = pytest.mark.django_db

SUPPLIER_LIST = reverse("catalog:supplier_list")
PRODUCT_LIST = reverse("catalog:product_list")


def supplier_data(**overrides):
    data = {
        "name": "Metal Construct SRL",
        "country": "RO",
        "tax_id": "RO14399840",
        "email": "office@metal.test",
        "phone": "",
        "address": "",
        "default_currency": "RON",
        "is_active": "on",
    }
    return data | overrides


# --- Listă și căutare -----------------------------------------------------------------


def test_list_search_by_name_tax_id_or_email(client, warehouse_user):
    SupplierFactory(name="Oțelăria Nord")
    SupplierFactory(name="Vopsele Sud", email="vanzari@vopsele.test")
    client.force_login(warehouse_user)

    by_name = client.get(SUPPLIER_LIST, {"q": "oțel"}).context["object_list"]
    by_email = client.get(SUPPLIER_LIST, {"q": "vopsele.test"}).context["object_list"]

    assert [s.name for s in by_name] == ["Oțelăria Nord"]
    assert [s.name for s in by_email] == ["Vopsele Sud"]


def test_list_status_filter(client, warehouse_user):
    SupplierFactory(name="Activ")
    SupplierFactory(name="Inactiv", is_active=False)
    client.force_login(warehouse_user)

    active = client.get(SUPPLIER_LIST, {"status": "active"}).context["object_list"]
    inactive = client.get(SUPPLIER_LIST, {"status": "inactive"}).context["object_list"]

    assert [s.name for s in active] == ["Activ"]
    assert [s.name for s in inactive] == ["Inactiv"]


def test_list_htmx_returns_only_the_table(client, warehouse_user):
    SupplierFactory()
    client.force_login(warehouse_user)

    html = client.get(SUPPLIER_LIST, headers={"HX-Request": "true"}).content.decode()

    assert "<html" not in html
    assert "<table" in html


def test_list_pagination(client, warehouse_user):
    ProductFactory.create_batch(25)
    client.force_login(warehouse_user)

    response = client.get(PRODUCT_LIST, {"page": 2})

    assert len(response.context["object_list"]) == 5


def test_add_button_only_for_editors(client, warehouse_user, procurement_user):
    create_url = reverse("catalog:supplier_create")

    client.force_login(warehouse_user)
    assert create_url not in client.get(SUPPLIER_LIST).content.decode()

    client.force_login(procurement_user)
    assert create_url in client.get(SUPPLIER_LIST).content.decode()


# --- Detaliu ----------------------------------------------------------------------------


def test_detail_shows_data_and_history(client, procurement_user, accounting_user):
    client.force_login(procurement_user)
    client.post(reverse("catalog:supplier_create"), supplier_data())
    supplier = Supplier.objects.get()
    client.force_login(accounting_user)

    html = client.get(supplier.get_absolute_url()).content.decode()

    assert "Metal Construct SRL" in html
    assert "14399840" in html
    assert "Istoric" in html and "Creare" in html
    assert reverse("catalog:supplier_update", args=[supplier.pk]) not in html  # nu poate edita


# --- Adăugare și editare ---------------------------------------------------------------


def test_create_supplier(client, procurement_user):
    client.force_login(procurement_user)

    response = client.post(reverse("catalog:supplier_create"), supplier_data(), follow=True)

    supplier = Supplier.objects.get()
    assert supplier.tax_id == "14399840"  # salvat fără prefixul RO
    assert response.redirect_chain[-1][0] == supplier.get_absolute_url()
    assert "a fost adăugat" in response.content.decode()
    entry = LogEntry.objects.get_for_object(supplier).get()
    assert entry.actor == procurement_user  # adăugarea a intrat în jurnal, cu autorul


def test_create_supplier_with_invalid_cui_shows_error(client, procurement_user):
    client.force_login(procurement_user)

    response = client.post(reverse("catalog:supplier_create"), supplier_data(tax_id="14399841"))

    assert response.status_code == 200
    assert "cifra de control" in response.content.decode()
    assert "is-invalid" in response.content.decode()  # câmpul e marcat cu roșu
    assert not Supplier.objects.exists()


def test_duplicate_cui_with_prefix_is_rejected_by_the_form(client, procurement_user):
    SupplierFactory(tax_id="14399840")
    client.force_login(procurement_user)

    response = client.post(reverse("catalog:supplier_create"), supplier_data(tax_id="RO14399840"))

    assert response.status_code == 200
    assert response.context["form"].errors["tax_id"]
    assert Supplier.objects.count() == 1


def test_deactivate_supplier(client, procurement_user):
    supplier = SupplierFactory(name="Vechi SRL", tax_id="14399840")
    client.force_login(procurement_user)

    client.post(
        reverse("catalog:supplier_update", args=[supplier.pk]),
        supplier_data(name="Vechi SRL", tax_id="14399840", is_active=""),
    )

    supplier.refresh_from_db()
    assert supplier.is_active is False


def test_create_product(client, procurement_user):
    client.force_login(procurement_user)

    client.post(
        reverse("catalog:product_create"),
        {
            "code": " mot-01 ",
            "name": "Motor 6 CP",
            "unit": "buc",
            "vat_rate": "21.00",
            "is_active": "on",
        },
    )

    product = Product.objects.get()
    assert product.code == "MOT-01"
    assert product.get_vat_rate_display() == "21% (standard)"


def test_product_detail(client, warehouse_user):
    product = ProductFactory(code="MOT-01", name="Motor 6 CP")
    client.force_login(warehouse_user)

    html = client.get(product.get_absolute_url()).content.decode()

    assert "MOT-01 – Motor 6 CP" in html
    assert "bucată (buc)" in html


def test_menu_items_are_now_active(client, warehouse_user):
    client.force_login(warehouse_user)

    html = client.get(reverse("dashboard:home")).content.decode()

    assert f'href="{SUPPLIER_LIST}"' in html
    assert f'href="{PRODUCT_LIST}"' in html


# --- Căutare tolerantă la diacritice și majuscule ------------------------------------


@pytest.mark.parametrize("query", ["dunarea", "DUNĂREA", "Oțel", "OȚELĂRIA", "otelaria dun"])
def test_search_ignores_diacritics_and_case(client, warehouse_user, query):
    """Utilizatorii tastează adesea fără diacritice sau cu Caps Lock."""
    SupplierFactory(name="Oțelăria Dunărea SRL", email="")
    SupplierFactory(name="Altceva SRL", email="")
    client.force_login(warehouse_user)

    results = client.get(SUPPLIER_LIST, {"q": query}).context["object_list"]

    assert [s.name for s in results] == ["Oțelăria Dunărea SRL"]


def test_search_text_follows_edits(client, procurement_user):
    supplier = SupplierFactory(name="Nume Vechi", tax_id="14399840")
    client.force_login(procurement_user)

    client.post(
        reverse("catalog:supplier_update", args=[supplier.pk]),
        supplier_data(name="Țesătoria Nouă", tax_id="14399840"),
    )

    results = client.get(SUPPLIER_LIST, {"q": "tesatoria"}).context["object_list"]
    assert [s.pk for s in results] == [supplier.pk]


def test_search_text_is_not_in_audit_log(procurement_user):
    supplier = SupplierFactory()

    entry = LogEntry.objects.get_for_object(supplier).get()

    assert "search_text" not in entry.changes_dict
