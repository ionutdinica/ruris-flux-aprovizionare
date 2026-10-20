"""Paginile de stoc: lista, registrul unui produs (cu sold), ieșiri și ajustări."""

from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory
from apps.purchasing.models import PurchaseOrder
from apps.warehouse import services
from apps.warehouse.selectors import available_stock

from .scenarios import receive, sent_order, status

pytestmark = pytest.mark.django_db

D = Decimal
STOCK = reverse("warehouse:stock")
MOVEMENT = reverse("warehouse:stock_movement")


@pytest.fixture
def stocked(warehouse_user):
    """10 bucăți recepționate (+ 2 în carantină) pe o comandă."""
    order = sent_order("10")
    receive(order, warehouse_user, "12")
    return order.lines.get()


def movement_data(product, kind="CONSUMPTION", quantity="3", **extra):
    return {
        "product": product.pk,
        "kind": kind,
        "quantity": quantity,
        "date": timezone.localdate().isoformat(),
        "reason": "Consum comanda de producție 45",
        **extra,
    }


# --- Lista ----------------------------------------------------------------------------------


def test_stock_list_shows_available_and_quarantine(client, accounting_user, stocked):
    ProductFactory()  # fără stoc
    client.force_login(accounting_user)  # toate rolurile văd stocul

    products = {p.pk: p for p in client.get(STOCK).context["object_list"]}
    product = products[stocked.product_id]

    assert (product.stock_available, product.stock_quarantined) == (D("10"), D("2"))


@pytest.mark.parametrize(
    ("status_filter", "expected"), [("available", 1), ("quarantine", 1), ("empty", 1)]
)
def test_stock_list_filters(client, warehouse_user, stocked, status_filter, expected):
    ProductFactory()
    client.force_login(warehouse_user)

    assert len(client.get(STOCK, {"status": status_filter}).context["object_list"]) == expected


# --- Registrul unui produs ---------------------------------------------------------------------


def test_ledger_with_running_balance(client, warehouse_user, stocked):
    services.record_stock_movement(stocked.product, "CONSUMPTION", D("4"), warehouse_user, "consum")
    services.record_stock_movement(
        stocked.product, "ADJUSTMENT_PLUS", D("1"), warehouse_user, "inventar"
    )
    client.force_login(warehouse_user)

    response = client.get(reverse("warehouse:stock_product", args=[stocked.product_id]))

    rows = [(m.quantity, m.balance) for m in response.context["page"].object_list]
    assert rows == [(D("1"), D("7")), (D("-4"), D("6")), (D("10"), D("10"))]  # cea mai nouă prima
    assert response.context["quarantined"] == D("2")
    assert "carantină" in response.content.decode()


def test_product_page_shows_stock_card(client, procurement_user, stocked):
    client.force_login(procurement_user)

    html = client.get(stocked.product.get_absolute_url()).content.decode()

    assert reverse("warehouse:stock_product", args=[stocked.product_id]) in html
    assert "Disponibil" in html


# --- Ieșiri și ajustări ---------------------------------------------------------------------


def test_record_consumption(client, warehouse_user, stocked):
    client.force_login(warehouse_user)

    response = client.post(MOVEMENT, movement_data(stocked.product), follow=True)

    assert available_stock(stocked.product) == D("7")
    assert response.redirect_chain[-1][0] == reverse(
        "warehouse:stock_product", args=[stocked.product_id]
    )
    assert "-3" in response.content.decode()


def test_exit_larger_than_stock_is_refused_with_explanation(client, warehouse_user, stocked):
    client.force_login(warehouse_user)

    response = client.post(MOVEMENT, movement_data(stocked.product, quantity="11"))

    assert response.status_code == 200
    assert "Stoc insuficient" in response.content.decode()
    assert available_stock(stocked.product) == D("10")


def test_return_on_order_line_via_form(client, warehouse_user, stocked):
    client.force_login(warehouse_user)

    client.post(
        MOVEMENT,
        movement_data(stocked.product, kind="SUPPLIER_RETURN", quantity="2", order_line=stocked.pk),
    )

    assert available_stock(stocked.product) == D("8")
    assert status(stocked.order) == PurchaseOrder.Status.PARTIALLY_RECEIVED


def test_product_fragment_for_htmx(client, warehouse_user, stocked):
    """La alegerea produsului, formularul primește stocul și liniile returnabile."""
    client.force_login(warehouse_user)

    response = client.get(
        reverse("warehouse:stock_movement_product"), {"product": stocked.product_id}
    )

    html = response.content.decode()
    assert 'id="product-dependent"' in html
    assert "10" in html  # stocul disponibil
    assert str(stocked.order) in html  # linia pe care se poate face retur


def test_form_preselects_product_from_link(client, warehouse_user, stocked):
    client.force_login(warehouse_user)

    response = client.get(MOVEMENT, {"produs": stocked.product_id})

    assert response.context["form"].initial["product"] == stocked.product
    assert response.context["available"] == D("10")


def test_menu_items_are_now_active(client, warehouse_user):
    client.force_login(warehouse_user)

    html = client.get(reverse("dashboard:home")).content.decode()

    assert f'href="{STOCK}"' in html
    assert f'href="{reverse("warehouse:discrepancy_list")}"' in html
