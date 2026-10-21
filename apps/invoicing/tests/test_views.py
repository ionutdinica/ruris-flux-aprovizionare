"""Paginile facturilor: listă, înregistrare cu linii, ecranul de potrivire, corectare."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.invoicing.models import Invoice
from apps.warehouse.tests.scenarios import receive, sent_order

from .scenarios import refreshed, register, validated

pytestmark = pytest.mark.django_db

D = Decimal
TODAY = timezone.localdate()
LIST = reverse("invoicing:invoice_list")
CREATE = reverse("invoicing:invoice_create")
OPTIONS = reverse("invoicing:order_line_options")


@pytest.fixture
def order(warehouse_user):
    """10 bucăți × 100 lei comandate, doar 6 recepționate."""
    order = sent_order("10")
    receive(order, warehouse_user, "6")
    return order


def form_data(order, lines, number="MI-1", **header):
    """Datele trimise de formular: antet + liniile [(linie de comandă, cantitate, preț)]."""
    data = {
        "supplier": order.supplier_id,
        "supplier_invoice_number": number,
        "currency": order.currency,
        "invoice_date": TODAY.isoformat(),
        "due_date": (TODAY + datetime.timedelta(days=30)).isoformat(),
        "declared_net": "600.00",
        "declared_vat": "126.00",
        "declared_total": "726.00",
        "notes": "",
        "lines-TOTAL_FORMS": str(len(lines)),
        "lines-INITIAL_FORMS": "0",
        "lines-MIN_NUM_FORMS": "0",
        "lines-MAX_NUM_FORMS": "1000",
        **header,
    }
    for index, (order_line, quantity, price) in enumerate(lines):
        data.update(
            {
                f"lines-{index}-order_line": order_line.pk,
                f"lines-{index}-quantity": quantity,
                f"lines-{index}-unit_price": price,
                f"lines-{index}-vat_rate": "21.00",
            }
        )
    return data


# --- Înregistrare ----------------------------------------------------------------------------


def test_register_and_validate_in_one_step(client, accounting_user, order):
    client.force_login(accounting_user)
    data = form_data(order, [(order.lines.get(), "6", "100")])

    response = client.post(CREATE, {**data, "validate": ""}, follow=True)

    invoice = Invoice.objects.get()
    assert invoice.status == Invoice.Status.MATCHED
    assert response.redirect_chain[-1][0] == invoice.get_absolute_url()
    assert "corespunde comenzii și recepției" in response.content.decode()


def test_save_without_validating(client, accounting_user, order):
    client.force_login(accounting_user)

    client.post(CREATE, form_data(order, [(order.lines.get(), "6", "100")]))

    assert Invoice.objects.get().status == Invoice.Status.REGISTERED


def test_blocked_invoice_explains_why(client, accounting_user, order):
    client.force_login(accounting_user)
    data = form_data(
        order,
        [(order.lines.get(), "10", "100")],
        declared_net="1000.00",
        declared_vat="210.00",
        declared_total="1210.00",
    )

    response = client.post(CREATE, {**data, "validate": ""}, follow=True)

    html = response.content.decode()
    assert "este blocată: 1 motiv" in html
    assert "recepționat doar 6 buc: 4 buc nesosite" in html
    assert 'class="table-danger"' in html  # rândul problemă e evidențiat


def test_line_of_another_supplier_is_refused(client, accounting_user, order):
    """Chiar dacă cineva ocolește lista din pagină, serverul refuză linia."""
    foreign = sent_order("5").lines.get()
    client.force_login(accounting_user)

    response = client.post(CREATE, form_data(order, [(foreign, "5", "100")]))

    assert response.status_code == 200
    assert not Invoice.objects.exists()
    assert "Selectați o opțiune validă" in response.content.decode()


def test_invoice_without_lines_is_refused(client, accounting_user, order):
    client.force_login(accounting_user)

    response = client.post(CREATE, form_data(order, []))

    assert "cel puțin o linie" in response.content.decode()
    assert not Invoice.objects.exists()


def test_duplicate_supplier_number_is_explained(client, accounting_user, order):
    existing = register(order, "1")
    client.force_login(accounting_user)
    data = form_data(
        order, [(order.lines.get(), "6", "100")], number=existing.supplier_invoice_number
    )

    response = client.post(CREATE, data)

    assert "a fost deja înregistrată" in response.content.decode()
    assert Invoice.objects.count() == 1


def test_supplier_preselected_from_link(client, accounting_user, order):
    client.force_login(accounting_user)

    response = client.get(CREATE, {"furnizor": order.supplier_id})

    form = response.context["form"]
    assert form.initial["supplier"] == order.supplier
    assert list(response.context["lines"].order_lines) == [order.lines.get()]


# --- Liniile de comandă ale furnizorului ---------------------------------------------------------


def test_options_only_for_the_chosen_supplier(client, accounting_user, order):
    other = sent_order("3")
    client.force_login(accounting_user)

    html = client.get(OPTIONS, {"furnizor": order.supplier_id}).content.decode()

    assert order.number in html and other.number not in html
    assert 'data-remaining="6"' in html  # recepționat 6, facturat 0
    assert 'data-price="100"' in html


def test_draft_orders_are_not_offered(client, accounting_user):
    from apps.purchasing.tests.factories import PurchaseOrderLineFactory

    draft_line = PurchaseOrderLineFactory()
    client.force_login(accounting_user)

    html = client.get(OPTIONS, {"furnizor": draft_line.order.supplier_id}).content.decode()

    assert draft_line.order.number not in html


# --- Lista ------------------------------------------------------------------------------------


def test_list_filters(client, procurement_user, order):
    blocked = validated(order, "10")
    registered = register(order, "2")
    old = register(order, "1", invoice_date=TODAY - datetime.timedelta(days=60))
    client.force_login(procurement_user)  # Achizițiile văd facturile, fără să le modifice

    attention = client.get(LIST, {"status": "attention"}).context["object_list"]
    overdue = client.get(LIST, {"status": "overdue"}).context["object_list"]

    assert set(attention) == {blocked, registered, old}
    assert list(overdue) == [old]


def test_procurement_sees_no_registration_button(client, procurement_user):
    client.force_login(procurement_user)

    assert CREATE not in client.get(LIST).content.decode()


# --- Ecranul de potrivire și corectarea ------------------------------------------------------


def test_detail_compares_declared_and_computed_totals(client, accounting_user, warehouse_user):
    order = sent_order("10")
    receive(order, warehouse_user, "10")
    invoice = validated(order, "10", declared=("1000.00", "210.00", "1300.00"))
    client.force_login(accounting_user)

    response = client.get(invoice.get_absolute_url())

    totals = response.context["totals"]
    assert [row["ok"] for row in totals] == [True, True, False]


def test_registered_invoice_can_be_edited(client, accounting_user, order):
    invoice = register(order, "6")
    client.force_login(accounting_user)

    response = client.get(reverse("invoicing:invoice_update", args=[invoice.pk]))

    assert response.status_code == 200


def test_blocked_invoice_must_be_reopened_before_editing(client, accounting_user, order):
    invoice = validated(order, "10")
    client.force_login(accounting_user)

    response = client.get(reverse("invoicing:invoice_update", args=[invoice.pk]), follow=True)

    assert "Redeschide-o pentru corectare" in response.content.decode()


def test_reopen_leads_to_the_edit_form(client, accounting_user, order):
    invoice = validated(order, "10")
    client.force_login(accounting_user)

    response = client.post(reverse("invoicing:invoice_reopen", args=[invoice.pk]))

    assert response.url == reverse("invoicing:invoice_update", args=[invoice.pk])
    assert refreshed(invoice).status == Invoice.Status.REGISTERED


def test_validate_button(client, accounting_user, order):
    invoice = register(order, "6")
    client.force_login(accounting_user)

    client.post(reverse("invoicing:invoice_validate", args=[invoice.pk]))

    assert refreshed(invoice).status == Invoice.Status.MATCHED


def test_procurement_cannot_validate(client, procurement_user, order):
    invoice = register(order, "6")
    client.force_login(procurement_user)

    response = client.post(reverse("invoicing:invoice_validate", args=[invoice.pk]))

    assert response.status_code == 403
    assert refreshed(invoice).status == Invoice.Status.REGISTERED


def test_history_is_readable(client, accounting_user, order):
    invoice = validated(order, "10")
    client.force_login(accounting_user)

    html = client.get(invoice.get_absolute_url()).content.decode()

    assert "Motive: marfă nesosită" in html
    assert "NOT_RECEIVED" not in html


def test_menu_item_is_now_active(client, accounting_user):
    client.force_login(accounting_user)

    html = client.get(reverse("dashboard:home")).content.decode()

    assert f'href="{LIST}"' in html
