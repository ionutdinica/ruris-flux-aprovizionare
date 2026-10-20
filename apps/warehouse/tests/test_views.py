"""Paginile depozitului: livrări așteptate, formularul recepției, confirmare, ștergere.

Accesul pe roluri (403) e verificat automat în apps/accounts/tests/test_url_permissions.py.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory, SupplierFactory
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.purchasing.services import cancel_order
from apps.warehouse.models import Discrepancy, GoodsReceipt
from apps.warehouse.selectors import available_stock

from .scenarios import receive, sent_order

pytestmark = pytest.mark.django_db

D = Decimal
TODAY = timezone.localdate()
EXPECTED = reverse("warehouse:expected")
RECEIPTS = reverse("warehouse:receipt_list")


def receipt_post(rows, *, total=None, initial=0, **header):
    """Datele trimise de formularul recepției. rows = {index: {câmp: valoare}}."""
    data = {
        "receipt_date": TODAY.isoformat(),
        "delivery_note": "AVZ-123",
        "notes": "",
        "lines-TOTAL_FORMS": total if total is not None else len(rows),
        "lines-INITIAL_FORMS": initial,
        "lines-MIN_NUM_FORMS": 0,
        "lines-MAX_NUM_FORMS": 1000,
        **header,
    }
    for index, fields in rows.items():
        for key, value in fields.items():
            data[f"lines-{index}-{key}"] = value
    return data


def set_line_dates(order, days):
    PurchaseOrderLine.objects.filter(order=order).update(expected_date=TODAY + timedelta(days=days))


# --- Livrări așteptate --------------------------------------------------------------------------


def test_expected_deliveries(client, warehouse_user):
    late, soon, done = sent_order("10"), sent_order("5"), sent_order("2")
    set_line_dates(late, -2)
    set_line_dates(soon, 3)
    receive(done, warehouse_user, "2")  # recepționată complet: nu mai e așteptată
    client.force_login(warehouse_user)

    response = client.get(EXPECTED)

    assert [o.pk for o in response.context["object_list"]] == [late.pk, soon.pk]  # după termen
    assert "întârziată" in response.content.decode()
    assert response.context["object_list"][0].pending_lines == 1


def test_expected_deliveries_filters(client, warehouse_user):
    late, today = sent_order("10"), sent_order("5")
    set_line_dates(late, -1)
    set_line_dates(today, 0)
    client.force_login(warehouse_user)

    assert [o.pk for o in client.get(EXPECTED, {"status": "late"}).context["object_list"]] == [
        late.pk
    ]
    assert [o.pk for o in client.get(EXPECTED, {"status": "today"}).context["object_list"]] == [
        today.pk
    ]


# --- Recepție pe comandă -----------------------------------------------------------------------


def test_receipt_form_shows_expected_quantities_without_prefilling(client, warehouse_user):
    order = sent_order("10", "4")
    client.force_login(warehouse_user)

    response = client.get(reverse("warehouse:receipt_from_order", args=[order.pk]))

    forms = response.context["lines"].forms
    assert [f.pending.remaining_qty for f in forms] == [D("10"), D("4")]
    # Câmpul „numărat” e gol: magazionerul trebuie să numere, nu să confirme o cifră.
    assert all(not f["quantity_received"].value() for f in forms)


def test_create_receipt_from_order(client, warehouse_user):
    order = sent_order("10", "4")
    extra_product = ProductFactory()
    client.force_login(warehouse_user)

    response = client.post(
        reverse("warehouse:receipt_from_order", args=[order.pk]),
        receipt_post(
            {
                0: {"quantity_received": "12"},  # 10 așteptate: 2 vor merge în carantină
                1: {"quantity_received": ""},  # nu a venit
                2: {"product": extra_product.pk, "quantity_received": "1"},  # nu e pe comandă
            }
        ),
    )

    receipt = GoodsReceipt.objects.get()
    assert response.url == receipt.get_absolute_url()
    assert receipt.is_draft and receipt.purchase_order == order
    assert receipt.lines.count() == 2  # linia care nu a venit nu e salvată
    preview = client.get(receipt.get_absolute_url()).context["preview"]
    assert [(accepted, quarantined) for _, accepted, quarantined in preview] == [
        (D("10"), D("2")),
        (D("0"), D("1")),
    ]


def test_order_rows_cannot_be_tampered_with(client, warehouse_user):
    """Produsul unui rând de pe comandă nu poate fi schimbat din browser."""
    order = sent_order("10")
    client.force_login(warehouse_user)

    client.post(
        reverse("warehouse:receipt_from_order", args=[order.pk]),
        receipt_post({0: {"quantity_received": "5", "product": ProductFactory().pk}}),
    )

    assert GoodsReceipt.objects.get().lines.get().product == order.lines.get().product


def test_extra_row_cannot_be_a_product_already_on_the_order(client, warehouse_user):
    order = sent_order("10")
    client.force_login(warehouse_user)

    response = client.post(
        reverse("warehouse:receipt_from_order", args=[order.pk]),
        receipt_post(
            {
                0: {"quantity_received": "5"},
                1: {"product": order.lines.get().product_id, "quantity_received": "2"},
            }
        ),
    )

    assert response.status_code == 200
    assert "completează cantitatea pe linia lui" in response.content.decode()
    assert not GoodsReceipt.objects.exists()


def test_cannot_start_receipt_on_cancelled_order(client, warehouse_user):
    order = sent_order("10")
    cancel_order(order, "anulată")
    client.force_login(warehouse_user)

    response = client.get(reverse("warehouse:receipt_from_order", args=[order.pk]), follow=True)

    assert response.redirect_chain[-1][0] == EXPECTED
    assert "nu se poate recepționa" in response.content.decode()


# --- Confirmare, editare, ștergere ----------------------------------------------------------------


def test_confirm_from_detail_page(client, warehouse_user):
    order = sent_order("10")
    receipt = receive(order, warehouse_user, "12", confirm=False)
    client.force_login(warehouse_user)

    response = client.post(reverse("warehouse:receipt_confirm", args=[receipt.pk]), follow=True)

    receipt.refresh_from_db()
    assert receipt.status == GoodsReceipt.Status.CONFIRMED
    assert available_stock(order.lines.get().product) == D("10")
    html = response.content.decode()
    assert f"Recepția {receipt.number} a fost confirmată" in html
    assert "1 linii au mers în carantină" in html
    assert "așteaptă decizia Achizițiilor" in html


def test_edit_draft_keeps_existing_lines_and_offers_the_rest(client, warehouse_user):
    order = sent_order("10", "4")
    draft = receive(order, warehouse_user, "3", confirm=False)  # doar prima linie
    client.force_login(warehouse_user)

    forms = client.get(reverse("warehouse:receipt_update", args=[draft.pk])).context["lines"].forms

    assert len(forms) == 2
    assert forms[0].instance.pk  # linia existentă
    assert forms[1].pending.remaining_qty == D("4")  # linia care lipsea, oferită din nou


def test_confirmed_receipt_cannot_be_edited(client, warehouse_user):
    receipt = receive(sent_order("10"), warehouse_user, "10")
    client.force_login(warehouse_user)

    response = client.get(reverse("warehouse:receipt_update", args=[receipt.pk]), follow=True)

    assert response.redirect_chain[-1][0] == receipt.get_absolute_url()
    assert "nu se mai poate modifica" in response.content.decode()


def test_delete_draft(client, warehouse_user):
    receipt = receive(sent_order("10"), warehouse_user, "10", confirm=False)
    client.force_login(warehouse_user)

    client.post(reverse("warehouse:receipt_delete", args=[receipt.pk]))

    assert not GoodsReceipt.objects.exists()


# --- Recepție fără comandă ------------------------------------------------------------------------


def test_receipt_without_order(client, warehouse_user):
    supplier, product = SupplierFactory(), ProductFactory()
    client.force_login(warehouse_user)

    client.post(
        reverse("warehouse:receipt_without_order"),
        receipt_post({0: {"product": product.pk, "quantity_received": "6"}}, supplier=supplier.pk),
    )
    receipt = GoodsReceipt.objects.get()
    client.post(reverse("warehouse:receipt_confirm", args=[receipt.pk]))

    assert receipt.purchase_order is None
    assert Discrepancy.objects.get().quantity == D("6")  # totul în carantină
    assert available_stock(product) == 0


def test_receipt_without_order_requires_supplier(client, warehouse_user):
    client.force_login(warehouse_user)

    response = client.post(reverse("warehouse:receipt_without_order"), receipt_post({}))

    assert response.context["form"].errors["supplier"]


# --- Lista și pagina comenzii ---------------------------------------------------------------------


def test_receipt_list_quarantine_filter(client, warehouse_user):
    with_quarantine = receive(sent_order("10"), warehouse_user, "12")
    receive(sent_order("10"), warehouse_user, "10")
    client.force_login(warehouse_user)

    response = client.get(RECEIPTS, {"status": "quarantine"})

    assert [r.pk for r in response.context["object_list"]] == [with_quarantine.pk]


def test_order_page_lists_receipts_and_offers_receiving(client, warehouse_user):
    order = sent_order("10")
    receipt = receive(order, warehouse_user, "4")
    client.force_login(warehouse_user)

    html = client.get(order.get_absolute_url()).content.decode()

    assert receipt.number in html
    assert reverse("warehouse:receipt_from_order", args=[order.pk]) in html
    assert PurchaseOrder.objects.get(pk=order.pk).status == PurchaseOrder.Status.PARTIALLY_RECEIVED


def test_menu_item_is_now_active(client, warehouse_user):
    client.force_login(warehouse_user)

    assert f'href="{RECEIPTS}"' in client.get(reverse("dashboard:home")).content.decode()
