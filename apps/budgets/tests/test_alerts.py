"""Alertele de buget: în panou și în emailul zilnic, pentru Achiziții și Contabilitate."""

from decimal import Decimal

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.budgets.models import SupplierBudget
from apps.catalog.tests.factories import SupplierFactory
from apps.notifications.alerts import alerts_for, collect
from apps.notifications.services import send_digest
from apps.warehouse.tests.scenarios import sent_order

pytestmark = pytest.mark.django_db

YEAR = timezone.localdate().year


def budget_with(committed_quantity, amount="10000", year=YEAR):
    """Furnizor cu buget `amount` lei și o comandă de `committed_quantity` × 100 lei."""
    supplier = SupplierFactory(name="Componente Electrice Banat SRL")
    sent_order(committed_quantity, supplier=supplier)  # înainte de buget: fără justificare
    SupplierBudget.objects.create(supplier=supplier, year=year, amount=Decimal(amount))
    return supplier


def budget_alerts():
    return [alert for alert in collect() if alert.code.startswith("BUDGET_")]


def test_below_90_percent_nothing_to_report():
    budget_with("89")

    assert budget_alerts() == []


def test_almost_used():
    supplier = budget_with("92")

    [alert] = budget_alerts()

    assert alert.code == "BUDGET_ALMOST_USED"
    assert alert.title == f"Buget {YEAR} · Componente Electrice Banat SRL"
    assert alert.detail == "Consumat 92%: mai sunt disponibili 800,00 RON din 10.000,00 RON."
    assert alert.url == supplier.get_absolute_url()


def test_exceeded():
    budget_with("115")

    [alert] = budget_alerts()

    assert alert.code == "BUDGET_EXCEEDED"
    assert alert.detail == "Depășit cu 1.500,00 RON: angajat 11.500,00 din 10.000,00 RON."


def test_exceeding_is_new_even_if_almost_used_was_reported():
    """Cheia conține nivelul: „depășit” apare ca NOU în emailul de a doua zi."""
    budget_with("115")
    budget = SupplierBudget.objects.get()

    assert budget_alerts()[0].key == f"BUDGET_EXCEEDED:{budget.pk}"


def test_only_this_years_budgets():
    budget_with("115", year=YEAR - 1)

    assert budget_alerts() == []


def test_who_is_told(procurement_user, accounting_user, warehouse_user):
    budget_with("95")

    assert [a.code for a in alerts_for(procurement_user)] == ["BUDGET_ALMOST_USED"]
    assert [a.code for a in alerts_for(accounting_user)] == ["BUDGET_ALMOST_USED"]
    assert alerts_for(warehouse_user) == []


def test_email_has_a_budgets_section(accounting_user):
    budget_with("95")

    send_digest(accounting_user)

    body = mail.outbox[0].body
    assert "== BUGETE ==" in body and "Buget " + str(YEAR) in body


def test_dashboard_lists_it(client, procurement_user):
    budget_with("115")
    client.force_login(procurement_user)

    html = client.get(reverse("dashboard:home")).content.decode()

    assert "Bugete" in html and "Depășit cu 1.500,00 RON" in html
