"""Paginile comenzilor: listă, filtre, formular cu linii, detaliu, acțiuni de status.

Accesul pe roluri (403) e verificat automat în apps/accounts/tests/test_url_permissions.py.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import BusinessEvent
from apps.catalog.tests.factories import ProductFactory, SupplierFactory
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine

from .factories import PurchaseOrderFactory, PurchaseOrderLineFactory

pytestmark = pytest.mark.django_db

Status = PurchaseOrder.Status
TODAY = timezone.localdate()
LIST = reverse("purchasing:order_list")
CREATE = reverse("purchasing:order_create")


def set_status(order, status):
    PurchaseOrder.objects.filter(pk=order.pk).update(status=status)
    order.refresh_from_db()


def form_data(supplier, owner, lines=(), *, existing=0, **header):
    """Datele trimise de formularul comenzii (antet + formset de linii)."""
    data = {
        "supplier": supplier.pk,
        "currency": "RON",
        "owner": owner.pk,
        "order_date": TODAY.isoformat(),
        "expected_date": (TODAY + timedelta(days=10)).isoformat(),
        "notes": "",
        "lines-TOTAL_FORMS": len(lines),
        "lines-INITIAL_FORMS": existing,
        "lines-MIN_NUM_FORMS": 0,
        "lines-MAX_NUM_FORMS": 1000,
    }
    data.update(header)
    for i, line in enumerate(lines):
        for key, value in line.items():
            data[f"lines-{i}-{key}"] = value
    return data


# --- Listă ------------------------------------------------------------------------------


def test_list_highlights_late_orders(client, procurement_user):
    late = PurchaseOrderFactory(
        order_date=TODAY - timedelta(days=20), expected_date=TODAY - timedelta(days=2)
    )
    PurchaseOrderLineFactory(order=late)
    set_status(late, Status.SENT)
    client.force_login(procurement_user)

    response = client.get(LIST, {"status": "late"})

    assert [o.pk for o in response.context["object_list"]] == [late.pk]
    assert "întârziată" in response.content.decode()


def test_list_filters_by_supplier(client, procurement_user):
    wanted = PurchaseOrderFactory()
    PurchaseOrderFactory()
    client.force_login(procurement_user)

    response = client.get(LIST, {"supplier": wanted.supplier_id})

    assert [o.pk for o in response.context["object_list"]] == [wanted.pk]


def test_drafts_are_hidden_from_other_teams(client, warehouse_user):
    draft = PurchaseOrderFactory()
    sent = PurchaseOrderFactory()
    set_status(sent, Status.SENT)
    client.force_login(warehouse_user)

    listed = [o.pk for o in client.get(LIST).context["object_list"]]

    assert listed == [sent.pk]
    assert client.get(draft.get_absolute_url()).status_code == 404


def test_warehouse_does_not_see_prices(client, warehouse_user):
    line = PurchaseOrderLineFactory(unit_price=Decimal("1234.50"))
    set_status(line.order, Status.SENT)
    client.force_login(warehouse_user)

    list_html = client.get(LIST).content.decode()
    detail_html = client.get(line.order.get_absolute_url()).content.decode()

    for html in (list_html, detail_html):
        assert "1.234,50" not in html
        assert "Valoare" not in html


def test_accounting_sees_prices(client, accounting_user):
    line = PurchaseOrderLineFactory(unit_price=Decimal("1234.50"))
    set_status(line.order, Status.SENT)
    client.force_login(accounting_user)

    html = client.get(line.order.get_absolute_url()).content.decode()

    assert "1.234,50" in html


# --- Formular: creare --------------------------------------------------------------------


def test_create_order_with_lines(client, procurement_user):
    supplier = SupplierFactory()
    motor, belt = ProductFactory(), ProductFactory(vat_rate=Decimal("11.00"))
    client.force_login(procurement_user)

    response = client.post(
        CREATE,
        form_data(
            supplier,
            procurement_user,
            [
                {"product": motor.pk, "quantity": "2", "unit_price": "1500", "vat_rate": "21.00"},
                {
                    "product": belt.pk,
                    "quantity": "10",
                    "unit_price": "25.5",
                    "vat_rate": "11.00",
                    "expected_date": (TODAY + timedelta(days=30)).isoformat(),
                },
            ],
        ),
    )

    order = PurchaseOrder.objects.get()
    assert response.url == order.get_absolute_url()
    assert order.status == Status.DRAFT
    assert order.net_amount == Decimal("3255.00")
    lines = list(order.lines.order_by("id"))
    assert lines[0].expected_date == order.expected_date  # termen gol → cel din antet
    assert lines[1].expected_date == TODAY + timedelta(days=30)


def test_create_form_shows_line_errors(client, procurement_user):
    client.force_login(procurement_user)

    response = client.post(
        CREATE,
        form_data(
            SupplierFactory(),
            procurement_user,
            [
                {
                    "product": ProductFactory().pk,
                    "quantity": "0",
                    "unit_price": "-1",
                    "vat_rate": "21.00",
                }
            ],
        ),
    )

    assert response.status_code == 200
    assert not PurchaseOrder.objects.exists()  # nimic salvat: antet și linii, împreună
    line_errors = response.context["lines"].forms[0].errors
    assert "quantity" in line_errors and "unit_price" in line_errors


def test_create_form_offers_only_active_suppliers(client, procurement_user):
    SupplierFactory(name="Activ SRL")
    SupplierFactory(name="Inactiv SRL", is_active=False)
    client.force_login(procurement_user)

    html = client.get(CREATE).content.decode()

    assert "Activ SRL" in html and "Inactiv SRL" not in html


def test_supplier_options_carry_default_currency(client, procurement_user):
    """Formularul propune moneda furnizorului (data-currency, folosit de formset.js)."""
    SupplierFactory(default_currency="EUR")
    client.force_login(procurement_user)

    html = client.get(CREATE).content.decode()

    assert 'data-currency="EUR"' in html


# --- Formular: editare după trimitere ------------------------------------------------------


@pytest.fixture
def sent_order():
    order = PurchaseOrderFactory()
    PurchaseOrderLineFactory(order=order, quantity=Decimal("10"), unit_price=Decimal("5"))
    set_status(order, Status.SENT)
    return order


def existing_line_data(line, **changes):
    data = {
        "id": line.pk,
        "order": line.order_id,
        "product": line.product_id,
        "quantity": f"{line.quantity}",
        "unit_price": f"{line.unit_price}",
        "vat_rate": f"{line.vat_rate}",
        "expected_date": line.expected_date.isoformat(),
    }
    return data | changes


def test_amend_sent_order_add_line_and_increase_quantity(client, procurement_user, sent_order):
    line = sent_order.lines.get()
    client.force_login(procurement_user)

    client.post(
        reverse("purchasing:order_update", args=[sent_order.pk]),
        form_data(
            sent_order.supplier,
            procurement_user,
            [
                existing_line_data(line, quantity="15", unit_price="999"),  # prețul e ignorat
                {
                    "product": ProductFactory().pk,
                    "quantity": "3",
                    "unit_price": "7",
                    "vat_rate": "21.00",
                },
            ],
            existing=1,
        ),
    )

    line.refresh_from_db()
    assert line.quantity == Decimal("15")
    assert line.unit_price == Decimal("5")  # câmp blocat după trimitere
    assert sent_order.lines.count() == 2


def test_amend_rejects_lower_quantity(client, procurement_user, sent_order):
    line = sent_order.lines.get()
    client.force_login(procurement_user)

    response = client.post(
        reverse("purchasing:order_update", args=[sent_order.pk]),
        form_data(
            sent_order.supplier,
            procurement_user,
            [existing_line_data(line, quantity="4")],
            existing=1,
        ),
    )

    assert response.status_code == 200
    assert "poate doar să crească" in response.content.decode()


def test_amend_rejects_deleting_lines(client, procurement_user, sent_order):
    line = sent_order.lines.get()
    client.force_login(procurement_user)

    response = client.post(
        reverse("purchasing:order_update", args=[sent_order.pk]),
        form_data(
            sent_order.supplier,
            procurement_user,
            [existing_line_data(line, DELETE="on")],
            existing=1,
        ),
    )

    assert response.status_code == 200
    assert PurchaseOrderLine.objects.filter(pk=line.pk).exists()


def test_closed_order_cannot_be_edited(client, procurement_user, sent_order):
    set_status(sent_order, Status.CANCELLED)
    client.force_login(procurement_user)

    response = client.get(reverse("purchasing:order_update", args=[sent_order.pk]), follow=True)

    assert response.redirect_chain[-1][0] == sent_order.get_absolute_url()
    assert "nu mai poate fi modificată" in response.content.decode()


# --- Acțiuni de status ------------------------------------------------------------------------


def test_send_from_detail_page(client, procurement_user):
    line = PurchaseOrderLineFactory()
    client.force_login(procurement_user)

    response = client.post(reverse("purchasing:order_send", args=[line.order_id]), follow=True)

    line.order.refresh_from_db()
    assert line.order.status == Status.SENT
    assert "a fost trimisă" in response.content.decode()
    assert (
        BusinessEvent.objects.get(event_type=BusinessEvent.Type.ORDER_SENT).actor
        == procurement_user
    )


def test_send_empty_order_shows_error(client, procurement_user):
    order = PurchaseOrderFactory()
    client.force_login(procurement_user)

    response = client.post(reverse("purchasing:order_send", args=[order.pk]), follow=True)

    assert "nu are nicio linie" in response.content.decode()


def test_transitions_require_post(client, procurement_user, sent_order):
    client.force_login(procurement_user)

    assert client.get(reverse("purchasing:order_send", args=[sent_order.pk])).status_code == 405


def test_cancel_requires_reason(client, procurement_user, sent_order):
    client.force_login(procurement_user)

    client.post(reverse("purchasing:order_cancel", args=[sent_order.pk]), {"reason": ""})
    sent_order.refresh_from_db()
    assert sent_order.status == Status.SENT

    client.post(
        reverse("purchasing:order_cancel", args=[sent_order.pk]), {"reason": "Preț prea mare"}
    )
    sent_order.refresh_from_db()
    assert sent_order.status == Status.CANCELLED


def test_detail_shows_actions_by_status(client, procurement_user, sent_order):
    client.force_login(procurement_user)

    html = client.get(sent_order.get_absolute_url()).content.decode()

    assert "Anulează" in html
    assert "Trimite comanda" not in html  # deja trimisă
    assert "Istoric" in html


def test_menu_item_is_now_active(client, warehouse_user):
    client.force_login(warehouse_user)

    assert f'href="{LIST}"' in client.get(reverse("dashboard:home")).content.decode()
