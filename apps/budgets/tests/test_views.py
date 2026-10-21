"""Pagina de bugete și formularele (accesul pe roluri e verificat automat în accounts)."""

from decimal import Decimal

import pytest
from auditlog.models import LogEntry
from django.urls import reverse
from django.utils import timezone

from apps.budgets.models import SupplierBudget
from apps.catalog.tests.factories import SupplierFactory
from apps.warehouse.tests.scenarios import sent_order

pytestmark = pytest.mark.django_db

YEAR = timezone.localdate().year
LIST = reverse("budgets:budget_list")


@pytest.fixture
def supplier():
    return SupplierFactory(name="Rulmenți Oltenia SRL", default_currency="RON")


def test_list_shows_the_four_figures(client, procurement_user, supplier):
    SupplierBudget.objects.create(supplier=supplier, year=YEAR, amount=Decimal("2000"))
    sent_order("19", supplier=supplier)  # 1.900 lei: 95%

    client.force_login(procurement_user)
    html = client.get(LIST).content.decode()

    assert "Rulmenți Oltenia SRL" in html
    assert "2.000,00 RON" in html and "1.900,00" in html and "100,00" in html
    assert "consumat 95%" in html and "aproape consumat" in html
    assert "Buget nou" not in html  # Achizițiile văd, nu stabilesc


def test_suppliers_without_budget_are_listed_with_a_shortcut(client, accounting_user, supplier):
    client.force_login(accounting_user)
    html = client.get(LIST).content.decode()

    assert "Niciun buget stabilit" in html
    assert f"furnizor={supplier.pk}" in html


def test_other_years_are_separate(client, accounting_user, supplier):
    SupplierBudget.objects.create(supplier=supplier, year=YEAR + 1, amount=Decimal("7000"))
    client.force_login(accounting_user)

    assert "7.000,00" not in client.get(LIST).content.decode()
    assert "7.000,00" in client.get(f"{LIST}?an={YEAR + 1}").content.decode()


def test_invalid_year_falls_back_to_the_current_one(client, accounting_user):
    client.force_login(accounting_user)

    assert client.get(f"{LIST}?an=abc").context["year"] == YEAR


def test_accounting_sets_a_budget(client, accounting_user, supplier):
    client.force_login(accounting_user)
    url = reverse("budgets:budget_create") + f"?an={YEAR}&furnizor={supplier.pk}"
    form = client.get(url).context["form"]
    assert (form.initial["year"], form.initial["supplier"]) == (YEAR, str(supplier.pk))

    response = client.post(
        url, {"supplier": supplier.pk, "year": YEAR, "amount": "60000", "notes": "Contract 12/2026"}
    )

    assert response.status_code == 302 and response.url == f"{LIST}?an={YEAR}"
    budget = SupplierBudget.objects.get()
    assert (budget.amount, budget.currency) == (Decimal("60000"), "RON")
    assert LogEntry.objects.get_for_object(budget).get().actor == accounting_user


def test_second_budget_for_the_same_year_is_refused(client, accounting_user, supplier):
    SupplierBudget.objects.create(supplier=supplier, year=YEAR, amount=Decimal("1"))
    client.force_login(accounting_user)

    response = client.post(
        reverse("budgets:budget_create"), {"supplier": supplier.pk, "year": YEAR, "amount": "5"}
    )

    assert response.status_code == 200
    assert "deja un buget" in response.content.decode()


def test_editing_changes_only_amount_and_notes(client, accounting_user, supplier):
    budget = SupplierBudget.objects.create(supplier=supplier, year=YEAR, amount=Decimal("100"))
    other = SupplierFactory()
    client.force_login(accounting_user)

    client.post(
        reverse("budgets:budget_update", args=[budget.pk]),
        {"supplier": other.pk, "year": YEAR + 5, "amount": "250", "notes": "Act adițional"},
    )

    budget.refresh_from_db()
    assert (budget.supplier, budget.year, budget.amount) == (supplier, YEAR, Decimal("250"))
    assert budget.notes == "Act adițional"


def test_menu_has_budgets_for_procurement_and_accounting(client, procurement_user, warehouse_user):
    client.force_login(procurement_user)
    assert LIST in client.get(reverse("dashboard:home")).content.decode()
    client.force_login(warehouse_user)
    assert LIST not in client.get(reverse("dashboard:home")).content.decode()
