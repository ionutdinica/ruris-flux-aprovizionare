"""Trimiterea unei comenzi față de bugetul furnizorului: avertisment, justificare, audit."""

from decimal import Decimal

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import BusinessEvent
from apps.budgets import services as budgets
from apps.budgets.models import SupplierBudget
from apps.catalog.tests.factories import SupplierFactory
from apps.purchasing import services as purchasing
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.tests.factories import PurchaseOrderFactory, PurchaseOrderLineFactory
from apps.warehouse.tests.scenarios import sent_order

pytestmark = pytest.mark.django_db

D = Decimal
YEAR = timezone.localdate().year
DRAFT, SENT = PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.SENT


@pytest.fixture
def supplier():
    """Buget 5.000 lei, din care 4.000 deja angajați: disponibil 1.000."""
    supplier = SupplierFactory(name="Plastic Injecție Dolj SRL", default_currency="RON")
    SupplierBudget.objects.create(supplier=supplier, year=YEAR, amount=D("5000"))
    sent_order("40", supplier=supplier)
    return supplier


def draft(supplier, quantity, owner=None):
    """Ciornă de `quantity` × 100 lei."""
    extra = {"owner": owner} if owner else {}
    order = PurchaseOrderFactory(supplier=supplier, **extra)
    PurchaseOrderLineFactory(order=order, quantity=D(quantity))
    return order


def last_event():
    return BusinessEvent.objects.order_by("-id").first()


# --- Regula ------------------------------------------------------------------------------------


def test_within_budget_is_sent_as_usual(supplier):
    order = budgets.send_order(draft(supplier, "10"))  # exact cât e disponibil

    assert order.status == SENT and order.budget_override_reason == ""
    assert last_event().event_type == BusinessEvent.Type.ORDER_SENT


def test_over_budget_without_a_reason_is_refused(supplier):
    order = draft(supplier, "15")

    with pytest.raises(purchasing.TransitionError, match="depășește bugetul .* cu 500,00 RON"):
        budgets.send_order(order, reason="   ")

    order.refresh_from_db()
    assert order.status == DRAFT


def test_over_budget_with_a_reason_is_sent_and_recorded(supplier):
    order = budgets.send_order(draft(supplier, "15"), reason="Linia 2 oprită, urgent.")

    assert order.status == SENT
    assert order.budget_override_reason == "Linia 2 oprită, urgent."
    event = last_event()
    assert event.event_type == BusinessEvent.Type.ORDER_SENT_OVER_BUDGET
    assert event.data == {"depășire": "500,00 RON", "justificare": "Linia 2 oprită, urgent."}
    assert event.target == order


def test_supplier_without_budget_is_not_checked():
    order = budgets.send_order(draft(SupplierFactory(), "1000"))

    assert order.status == SENT


def test_a_reason_given_when_not_needed_is_ignored(supplier):
    order = budgets.send_order(draft(supplier, "1"), reason="nu e cazul")

    assert order.budget_override_reason == ""


# --- Paginile ----------------------------------------------------------------------------------


def test_order_page_shows_the_budget_and_the_draft_effect(client, procurement_user, supplier):
    order = draft(supplier, "4", owner=procurement_user)
    client.force_login(procurement_user)

    html = client.get(order.get_absolute_url()).content.decode()

    assert "Buget " + str(YEAR) in html and "consumat 80%" in html
    assert "Această comandă: 400,00 RON" in html and "După trimitere rămân 600,00" in html
    assert 'name="reason"' not in html.split('id="sendModal"')[1].split("</form>")[0]


def test_send_window_asks_for_a_reason_when_over_budget(client, procurement_user, supplier):
    order = draft(supplier, "15", owner=procurement_user)
    client.force_login(procurement_user)

    modal = client.get(order.get_absolute_url()).content.decode().split('id="sendModal"')[1]

    assert "Depășește bugetul" in modal and "500,00 RON" in modal
    assert 'name="reason"' in modal and "Trimite peste buget" in modal


def test_sending_over_budget_through_the_page(client, procurement_user, supplier):
    order = draft(supplier, "15", owner=procurement_user)
    client.force_login(procurement_user)
    url = reverse("purchasing:order_send", args=[order.pk])

    refused = client.post(url, {"reason": ""})
    order.refresh_from_db()
    assert order.status == DRAFT
    assert "Se poate trimite doar cu o justificare" in str(list(get_messages(refused.wsgi_request)))

    client.post(url, {"reason": "Comandă aprobată de director."})
    order.refresh_from_db()
    assert order.status == SENT
    html = client.get(order.get_absolute_url()).content.decode()
    assert "Trimisă peste bugetul furnizorului" in html and "aprobată de director" in html


def test_warehouse_sees_neither_budget_nor_reason(client, warehouse_user, supplier):
    order = budgets.send_order(draft(supplier, "15"), reason="Urgent.")
    client.force_login(warehouse_user)

    html = client.get(order.get_absolute_url()).content.decode()

    assert "Buget " + str(YEAR) not in html and "Urgent." not in html


def test_supplier_page_shows_the_budget(client, accounting_user, supplier):
    client.force_login(accounting_user)

    html = client.get(supplier.get_absolute_url()).content.decode()

    assert "consumat 80%" in html and "1.000,00" in html


def test_supplier_without_budget_offers_to_set_one(client, accounting_user, procurement_user):
    supplier = SupplierFactory()
    client.force_login(accounting_user)
    assert "Stabilește buget" in client.get(supplier.get_absolute_url()).content.decode()
    client.force_login(procurement_user)
    assert "Stabilește buget" not in client.get(supplier.get_absolute_url()).content.decode()


def test_an_order_already_sent_is_refused_by_the_orders_rule(supplier):
    order = budgets.send_order(draft(supplier, "1"))

    with pytest.raises(purchasing.TransitionError, match="Doar o comandă în ciornă"):
        budgets.send_order(order)


def test_orders_never_record_an_overrun_without_a_reason(supplier):
    """Plasa de siguranță din comenzi, chiar dacă cineva ocolește modulul de bugete."""
    with pytest.raises(purchasing.TransitionError, match="Motivul este obligatoriu"):
        purchasing.send_order(draft(supplier, "15"), budget_excess="500,00 RON")
