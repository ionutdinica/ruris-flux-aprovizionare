"""Calculul bugetelor: ce consumă bugetul, ce nu, și efectul unei comenzi noi."""

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.budgets import services
from apps.budgets.models import SupplierBudget
from apps.catalog.tests.factories import SupplierFactory
from apps.currency.bnr import PublishedRate
from apps.currency.services import store_rates
from apps.invoicing.tests.scenarios import validated
from apps.purchasing import services as purchasing
from apps.purchasing.tests.factories import PurchaseOrderFactory, PurchaseOrderLineFactory
from apps.warehouse.tests.scenarios import receive, sent_order

pytestmark = pytest.mark.django_db

D = Decimal
TODAY = timezone.localdate()
YEAR = TODAY.year


@pytest.fixture
def supplier():
    return SupplierFactory(default_currency="RON")


def budget(supplier, amount, year=YEAR):
    return SupplierBudget.objects.create(supplier=supplier, year=year, amount=D(amount))


def draft(supplier, *quantities, currency="RON", order_date=TODAY):
    """O ciornă cu linii de 100 lei/buc (fără TVA)."""
    order = PurchaseOrderFactory(supplier=supplier, currency=currency, order_date=order_date)
    for quantity in quantities:
        PurchaseOrderLineFactory(order=order, quantity=D(quantity))
    return order


def status(supplier, year=YEAR):
    return services.status_for(supplier, year)


# --- Ce consumă bugetul ---------------------------------------------------------------------


def test_sent_orders_consume_the_budget_without_vat(supplier):
    budget(supplier, "5000")
    sent_order("10", "5", supplier=supplier)  # 15 × 100 lei

    result = status(supplier)

    assert result.committed == D("1500.00")
    assert result.available == D("3500.00")
    assert (result.percent, result.level) == (30, "ok")


def test_drafts_and_cancelled_orders_do_not_count(supplier):
    budget(supplier, "5000")
    draft(supplier, "10")
    purchasing.cancel_order(sent_order("20", supplier=supplier), "Renunțăm.")

    assert status(supplier).committed == 0


def test_closed_order_counts_only_what_arrived(supplier, warehouse_user):
    budget(supplier, "5000")
    order = sent_order("10", supplier=supplier)
    receive(order, warehouse_user, "4")
    purchasing.close_order(order, "Restul nu mai vine.")

    assert status(supplier).committed == D("400.00")


def test_only_orders_of_that_year(supplier):
    budget(supplier, "5000")
    last_year = PurchaseOrderFactory(supplier=supplier, order_date=datetime.date(YEAR - 1, 12, 30))
    PurchaseOrderLineFactory(order=last_year, quantity=D("10"))
    purchasing.send_order(last_year)

    assert status(supplier).committed == 0


def test_invoiced_part_is_shown_but_not_added_again(supplier, warehouse_user):
    budget(supplier, "5000")
    order = sent_order("10", supplier=supplier)
    receive(order, warehouse_user, "10")
    validated(order, "6")

    result = status(supplier)

    assert (result.committed, result.invoiced) == (D("1000.00"), D("600.00"))


def test_other_suppliers_do_not_count(supplier):
    budget(supplier, "5000")
    sent_order("10")

    assert status(supplier).committed == 0


def test_no_budget_no_status(supplier):
    assert status(supplier) is None


# --- Nivelurile ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("quantity", "level", "percent"),
    [("89", "ok", 89), ("90", "warning", 90), ("100", "warning", 100), ("101", "over", 101)],
)
def test_levels(supplier, quantity, level, percent):
    sent_order(quantity, supplier=supplier)  # înainte de buget: fără verificare la trimitere
    budget(supplier, "10000")

    result = status(supplier)

    assert (result.level, result.percent) == (level, percent)
    assert result.bar_percent == min(percent, 100)


def test_overrun(supplier):
    sent_order("12", supplier=supplier)
    budget(supplier, "1000")

    assert status(supplier).overrun == D("200.00")


# --- Monede ----------------------------------------------------------------------------------


def test_order_in_another_currency_is_converted_at_the_bnr_rate():
    store_rates([PublishedRate(TODAY - datetime.timedelta(days=3), "EUR", D("5.0000"), 1)])
    supplier = SupplierFactory(default_currency="EUR")
    budget(supplier, "1000")  # în EUR, moneda furnizorului
    purchasing.send_order(draft(supplier, "10"))  # comandă în lei: 1.000 lei = 200 EUR

    assert status(supplier).committed == D("200.00")


def test_without_any_rate_the_order_is_listed_apart(supplier):
    budget(supplier, "1000")
    order = draft(supplier, "1", currency="EUR")
    purchasing.send_order(order)

    result = status(supplier)

    assert result.committed == 0 and result.unconverted == [order]


# --- Efectul unei comenzi noi ---------------------------------------------------------------


def test_impact_of_a_draft_within_budget(supplier):
    budget(supplier, "5000")
    sent_order("30", supplier=supplier)

    impact = services.order_impact(draft(supplier, "15"))

    assert impact.amount == D("1500.00")
    assert impact.available_after == D("500.00")
    assert not impact.exceeds and impact.excess == 0


def test_impact_of_a_draft_over_budget(supplier):
    budget(supplier, "5000")
    sent_order("40", supplier=supplier)

    impact = services.order_impact(draft(supplier, "15"))

    assert impact.exceeds and impact.excess == D("500.00")


def test_when_the_budget_is_already_exceeded_the_whole_order_is_excess(supplier):
    sent_order("12", supplier=supplier)
    budget(supplier, "1000")  # stabilit (sau micșorat) după comandă: deja depășit

    impact = services.order_impact(draft(supplier, "3"))

    assert impact.excess == D("300.00")


def test_no_budget_no_impact(supplier):
    assert services.order_impact(draft(supplier, "15")) is None


def test_the_budget_of_the_orders_year_applies(supplier):
    budget(supplier, "100", year=YEAR + 1)

    assert services.order_impact(draft(supplier, "15")) is None


# --- Modelul -----------------------------------------------------------------------------------


def test_one_budget_per_supplier_and_year(supplier):
    from django.core.exceptions import ValidationError

    budget(supplier, "1000")

    with pytest.raises(ValidationError, match="deja un buget"):
        SupplierBudget(supplier=supplier, year=YEAR, amount=D("5")).full_clean()


def test_budget_takes_the_supplier_currency():
    supplier = SupplierFactory(default_currency="EUR")

    assert budget(supplier, "10").currency == "EUR"
