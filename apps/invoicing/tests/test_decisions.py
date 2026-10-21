"""Deciziile din pagina facturii (aprobare, forțare, plată, respingere) și legătura cu comanda."""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import BusinessEvent
from apps.invoicing.models import Invoice
from apps.invoicing.services import approve_invoice
from apps.warehouse.tests.scenarios import receive, sent_order

from .scenarios import refreshed, register, validated

pytestmark = pytest.mark.django_db

S = Invoice.Status
TODAY = timezone.localdate()


def url(name, invoice):
    return reverse(f"invoicing:{name}", args=[invoice.pk])


@pytest.fixture
def order(warehouse_user):
    """10 bucăți comandate, 6 recepționate."""
    order = sent_order("10")
    receive(order, warehouse_user, "6")
    return order


@pytest.fixture
def matched(order):
    return validated(order, "6")


@pytest.fixture
def blocked(order):
    return validated(order, "10")


# --- Aprobare și plată ------------------------------------------------------------------------


def test_approve_then_pay(client, accounting_user, matched):
    client.force_login(accounting_user)

    client.post(url("invoice_approve", matched))
    response = client.post(
        url("invoice_pay", matched),
        {"paid_at": TODAY.isoformat(), "reference": "OP 77"},
        follow=True,
    )

    invoice = refreshed(matched)
    assert (invoice.status, invoice.approved_by, invoice.payment_reference) == (
        S.PAID,
        accounting_user,
        "OP 77",
    )
    assert "marcată plătită" in response.content.decode()


def test_payment_needs_a_date(client, accounting_user, matched):
    approve_invoice(matched, accounting_user)
    client.force_login(accounting_user)

    response = client.post(url("invoice_pay", matched), {"paid_at": ""}, follow=True)

    assert refreshed(matched).status == S.APPROVED
    assert "obligatoriu" in response.content.decode()


def test_blocked_invoice_cannot_be_approved_via_page(client, accounting_user, blocked):
    client.force_login(accounting_user)

    response = client.post(url("invoice_approve", blocked), follow=True)

    assert refreshed(blocked).status == S.BLOCKED
    assert "Doar o factură potrivită poate fi aprobată" in response.content.decode()


# --- Forțare -----------------------------------------------------------------------------------


def test_force_without_reason_explains_the_rule(client, accounting_user, blocked):
    client.force_login(accounting_user)

    response = client.post(url("invoice_force", blocked), {"reason": ""}, follow=True)

    assert refreshed(blocked).status == S.BLOCKED
    assert "Justificarea este obligatorie" in response.content.decode()


def test_forced_invoice_stays_marked(client, accounting_user, procurement_user, blocked):
    client.force_login(accounting_user)
    client.post(url("invoice_force", blocked), {"reason": "Acord telefonic cu dl. Ionescu"})

    client.force_login(procurement_user)
    html = client.get(blocked.get_absolute_url()).content.decode()

    assert refreshed(blocked).status == S.APPROVED
    assert "Forțată la plată, deși era blocată" in html
    assert "Acord telefonic cu dl. Ionescu" in html
    assert BusinessEvent.objects.filter(event_type="invoice.force_approved").exists()


# --- Respingere --------------------------------------------------------------------------------


def test_reject(client, accounting_user, blocked):
    client.force_login(accounting_user)

    client.post(url("invoice_reject", blocked), {"reason": "Cerem stornare"})

    assert refreshed(blocked).rejection_reason == "Cerem stornare"


# --- Ce vede fiecare rol ------------------------------------------------------------------------


def test_buttons_follow_the_status(client, accounting_user, matched, blocked):
    client.force_login(accounting_user)

    matched_html = client.get(matched.get_absolute_url()).content.decode()
    blocked_html = client.get(blocked.get_absolute_url()).content.decode()

    assert "Aprobă la plată" in matched_html and "Forțează la plată" not in matched_html
    assert "Forțează la plată" in blocked_html and "Aprobă la plată" not in blocked_html


def test_procurement_sees_status_but_no_payment_details(
    client, accounting_user, procurement_user, matched
):
    """docs/04-permisiuni.md: Achizițiile văd statusul, nu și detaliile plății."""
    approve_invoice(matched, accounting_user)
    client.force_login(accounting_user)
    client.post(url("invoice_pay", matched), {"paid_at": TODAY.isoformat(), "reference": "OP 9"})

    client.force_login(procurement_user)
    html = client.get(matched.get_absolute_url()).content.decode()

    assert "Plătită" in html
    assert "OP 9" not in html
    assert "Marchează plătită" not in html and "Respinge" not in html


@pytest.mark.parametrize("action", ["invoice_approve", "invoice_force", "invoice_reject"])
def test_procurement_cannot_decide(client, procurement_user, blocked, action):
    client.force_login(procurement_user)

    assert client.post(url(action, blocked), {"reason": "x"}).status_code == 403
    assert refreshed(blocked).status == S.BLOCKED


# --- Legătura cu comanda -----------------------------------------------------------------------


def test_order_page_lists_its_invoices(client, accounting_user, order):
    first, second = validated(order, "6"), register(order, "1")
    client.force_login(accounting_user)

    response = client.get(order.get_absolute_url())

    assert list(response.context["invoices"]) == [first, second]
    assert "Înregistrează factura" in response.content.decode()


def test_warehouse_does_not_see_invoices_on_the_order(client, warehouse_user, matched, order):
    client.force_login(warehouse_user)

    response = client.get(order.get_absolute_url())

    assert "invoices" not in response.context
    assert matched.number not in response.content.decode()


def test_register_from_order_prefills_what_is_left_to_invoice(client, accounting_user, order):
    validated(order, "4")  # din 6 sosite, 4 deja facturate
    client.force_login(accounting_user)

    response = client.get(reverse("invoicing:invoice_create"), {"comanda": order.pk})

    lines = response.context["lines"]
    assert response.context["form"].initial["supplier"] == order.supplier
    assert [form.initial["quantity"] for form in lines.forms] == ["2"]
    assert lines.forms[0].initial["order_line"] == order.lines.get()


def test_accounting_still_sees_payment_details_in_history(client, accounting_user, matched):
    """Ascunderea e doar pentru cine nu are permisiunea, nu pentru toată lumea."""
    approve_invoice(matched, accounting_user)
    client.force_login(accounting_user)
    client.post(url("invoice_pay", matched), {"paid_at": TODAY.isoformat(), "reference": "OP 9"})

    html = client.get(matched.get_absolute_url()).content.decode()

    assert "Referința: OP 9" in html
    assert f"Data plății: {TODAY:%d.%m.%Y}" in html
