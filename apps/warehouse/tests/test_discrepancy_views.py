"""Paginile discrepanțelor: listă, decizia Achizițiilor (atașare, surplus, retur)."""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.catalog.tests.factories import ProductFactory, SupplierFactory
from apps.purchasing.models import PurchaseOrderLine
from apps.warehouse.models import Discrepancy
from apps.warehouse.selectors import available_stock

from .scenarios import receive, receive_without_order, sent_order

pytestmark = pytest.mark.django_db

D = Decimal
LIST = reverse("warehouse:discrepancy_list")


@pytest.fixture
def surplus(warehouse_user):
    """Comandat 10, venit 12: 2 în carantină."""
    order = sent_order("10")
    receive(order, warehouse_user, "12")
    return Discrepancy.objects.get()


@pytest.fixture
def unordered(warehouse_user):
    supplier = SupplierFactory(name="Oțelăria Dunărea SRL")
    receive_without_order(supplier, warehouse_user, (ProductFactory(name="Tablă oțel 2 mm"), "3"))
    return Discrepancy.objects.get()


# --- Listă -----------------------------------------------------------------------------------


def test_list_shows_open_first_and_filters(client, procurement_user, warehouse_user, surplus):
    resolved = surplus
    resolved_product = resolved.product
    client.force_login(procurement_user)
    client.post(reverse("warehouse:discrepancy_return", args=[resolved.pk]), {"note": "retur"})
    receive_without_order(SupplierFactory(), warehouse_user, (ProductFactory(), "1"))

    all_items = client.get(LIST).context["object_list"]
    open_items = client.get(LIST, {"status": "OPEN"}).context["object_list"]

    assert [d.status for d in all_items] == ["OPEN", "RESOLVED"]  # deschisele primele
    assert len(open_items) == 1 and open_items[0].product != resolved_product


def test_search_through_related_documents_without_diacritics(client, procurement_user, unordered):
    client.force_login(procurement_user)

    by_supplier = client.get(LIST, {"q": "otelaria"}).context["object_list"]
    by_product = client.get(LIST, {"q": "TABLA OTEL"}).context["object_list"]

    assert list(by_supplier) == list(by_product) == [unordered]


# --- Pagina de decizie ---------------------------------------------------------------------------


def test_procurement_sees_the_three_options(client, procurement_user, surplus):
    client.force_login(procurement_user)

    html = client.get(surplus.get_absolute_url()).content.decode()

    assert "Acceptă surplusul" in html
    assert "crește de la <strong>10</strong> la <strong>12" in html
    assert "Atașez marfa la o comandă" in html
    assert "Returnez marfa furnizorului" in html


def test_warehouse_sees_no_decision_buttons(client, warehouse_user, surplus):
    client.force_login(warehouse_user)

    html = client.get(surplus.get_absolute_url()).content.decode()

    assert "Acceptă surplusul" not in html
    assert "decid ce se întâmplă cu ea" in html


def test_attach_via_page(client, procurement_user, unordered):
    order = sent_order("5", supplier=unordered.supplier, products=[unordered.product])
    line = order.lines.get()
    client.force_login(procurement_user)

    page = client.get(unordered.get_absolute_url())
    assert list(page.context["candidates"]) == [line]
    response = client.post(
        reverse("warehouse:discrepancy_attach", args=[unordered.pk]),
        {"order_line": line.pk, "note": "OK telefonic"},
        follow=True,
    )

    unordered.refresh_from_db()
    assert unordered.resolution == Discrepancy.Resolution.ATTACHED
    assert available_stock(unordered.product) == D("3")
    assert f"atașată comenzii {order}" in response.content.decode()


def test_attach_rejects_a_line_outside_the_candidates(client, procurement_user, unordered):
    foreign_line = sent_order("5").lines.get()  # alt furnizor, alt produs
    client.force_login(procurement_user)

    response = client.post(
        reverse("warehouse:discrepancy_attach", args=[unordered.pk]),
        {"order_line": foreign_line.pk},
        follow=True,
    )

    unordered.refresh_from_db()
    assert unordered.is_open
    assert "Alege una dintre liniile de comandă propuse" in response.content.decode()


def test_no_candidates_suggests_regularization(client, procurement_user, unordered):
    client.force_login(procurement_user)

    html = client.get(unordered.get_absolute_url()).content.decode()

    assert "adaugă o linie pe o comandă (regularizare)" in html


def test_accept_surplus_via_page(client, procurement_user, surplus):
    client.force_login(procurement_user)

    client.post(reverse("warehouse:discrepancy_accept_surplus", args=[surplus.pk]), {"note": ""})

    line = PurchaseOrderLine.objects.get(pk=surplus.receipt_line.order_line_id)
    assert line.quantity == D("12")
    assert available_stock(line.product) == D("12")


def test_return_requires_reason_via_page(client, procurement_user, surplus):
    client.force_login(procurement_user)

    response = client.post(
        reverse("warehouse:discrepancy_return", args=[surplus.pk]), {"note": ""}, follow=True
    )
    surplus.refresh_from_db()
    assert surplus.is_open
    assert "obligatoriu" in response.content.decode()

    client.post(reverse("warehouse:discrepancy_return", args=[surplus.pk]), {"note": "Defecte"})
    surplus.refresh_from_db()
    assert surplus.resolution == Discrepancy.Resolution.RETURNED


def test_receipt_page_links_to_the_discrepancy(client, warehouse_user, surplus):
    client.force_login(warehouse_user)

    html = client.get(surplus.receipt.get_absolute_url()).content.decode()

    assert surplus.get_absolute_url() in html
