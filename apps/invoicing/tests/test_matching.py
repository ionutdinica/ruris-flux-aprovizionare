"""Motorul de potrivire în 3 direcții: fiecare regulă din docs/05-reguli-business.md, §1."""

from decimal import Decimal

import pytest

from apps.catalog.tests.factories import SupplierFactory
from apps.currency.bnr import PublishedRate
from apps.currency.services import store_rates
from apps.invoicing.matching import find_problems
from apps.invoicing.models import Invoice
from apps.invoicing.services import approve_invoice, recheck_order, validate_invoice
from apps.purchasing import services as purchasing
from apps.purchasing.models import PurchaseOrderLine
from apps.purchasing.tests.factories import PurchaseOrderLineFactory
from apps.warehouse import services as warehouse
from apps.warehouse.models import Discrepancy
from apps.warehouse.tests.scenarios import receive, sent_order

from .scenarios import codes, messages, refreshed, register, validated

pytestmark = pytest.mark.django_db

D = Decimal
MATCHED, BLOCKED = Invoice.Status.MATCHED, Invoice.Status.BLOCKED


@pytest.fixture
def order(warehouse_user):
    """Comandă de 10 bucăți × 100,00 lei (TVA 21%), recepționată complet."""
    order = sent_order("10")
    receive(order, warehouse_user, "10")
    return order


def supplier_return(order_line, quantity, user):
    warehouse.record_stock_movement(
        order_line.product, "SUPPLIER_RETURN", D(quantity), user, "Defecte", order_line=order_line
    )


# --- Cazul fericit -------------------------------------------------------------------------


def test_invoice_matching_order_and_receipt(order):
    invoice = validated(order, "10")

    assert refreshed(invoice).status == MATCHED
    assert codes(invoice) == []


def test_invoice_covering_two_orders_of_the_same_supplier(warehouse_user):
    """I-18: o factură poate acoperi mai multe comenzi ale aceluiași furnizor."""
    first = sent_order("5")
    second = sent_order("3", supplier=first.supplier)
    receive(first, warehouse_user, "5")
    receive(second, warehouse_user, "3")

    invoice = validated(first, lines=[(first.lines.get(), "5"), (second.lines.get(), "3")])

    assert refreshed(invoice).status == MATCHED


def test_partial_invoices_are_fine(order):
    """I-18: aceeași comandă, facturată în două facturi."""
    assert refreshed(validated(order, "6")).status == MATCHED
    assert refreshed(validated(order, "4")).status == MATCHED


# --- Cantități ---------------------------------------------------------------------------


def test_not_received(warehouse_user):
    order = sent_order("10")
    receive(order, warehouse_user, "6")

    invoice = validated(order, "10")

    assert codes(invoice) == ["NOT_RECEIVED"]
    assert "facturat 10 buc, recepționat doar 6 buc: 4 buc nesosite" in messages(invoice)


def test_over_ordered_reports_every_problem_at_once(order):
    """Facturat 12, comandat 10, recepționat 10: două motive, afișate împreună."""
    invoice = validated(order, "12")

    assert codes(invoice) == ["NOT_RECEIVED", "OVER_ORDERED"]
    assert "facturat 12 buc, comandat 10 buc" in messages(invoice)


def test_same_goods_on_a_second_invoice_are_blocked(order):
    """Protecția la dublă plată: aceeași marfă, pe două facturi diferite."""
    first = validated(order, "10")
    second = validated(order, "10")

    assert refreshed(first).status == MATCHED
    assert codes(second) == ["NOT_RECEIVED", "OVER_ORDERED"]
    assert "facturat 20 buc (din care 10 pe facturi anterioare)" in messages(second)


def test_quarantined_goods_do_not_count_as_received(warehouse_user):
    """Venit 12 pe o comandă de 10: cele 2 în plus sunt în carantină, nu „recepționate”."""
    order = sent_order("10")
    receive(order, warehouse_user, "12")

    invoice = validated(order, "12")

    assert "recepționat doar 10 buc" in messages(invoice)


def test_duplicate_line(order):
    line = order.lines.get()
    invoice = validated(order, lines=[(line, "4"), (line, "4")])

    assert codes(invoice) == ["DUPLICATE_LINE"]
    assert "apare de 2 ori pe factură" in messages(invoice)


def test_order_line_added_later_and_not_received_yet(warehouse_user):
    order = sent_order("10")
    receive(order, warehouse_user, "10")
    extra = PurchaseOrderLineFactory(order=order, quantity=D("3"))

    invoice = validated(order, lines=[(order.lines.order_by("id")[0], "10"), (extra, "3")])

    assert codes(invoice) == ["NOT_RECEIVED"]


# --- Prețuri și totaluri -----------------------------------------------------------------


def test_price_mismatch(order):
    invoice = validated(order, "10", prices=["105.00"])

    assert codes(invoice) == ["PRICE_MISMATCH"]
    assert "preț 105,00 RON față de 100,00 RON în comanda" in messages(invoice)
    assert "(+5,0%)" in messages(invoice)


def test_price_within_configured_tolerance(order, settings):
    settings.PRICE_TOLERANCE_PERCENT = D("5")

    assert codes(validated(order, "5", prices=["105.00"])) == []
    assert codes(validated(order, "5", prices=["105.01"])) == ["PRICE_MISMATCH"]


def test_cheaper_than_ordered_is_also_reported(order):
    """Orice diferență se verifică: un preț mai mic poate fi altă marfă sau o greșeală."""
    assert codes(validated(order, "10", prices=["99.00"])) == ["PRICE_MISMATCH"]


@pytest.mark.parametrize(
    ("declared_total", "expected"),
    [("1210.05", []), ("1209.95", []), ("1210.06", ["TOTAL_MISMATCH"])],
)
def test_total_rounding_tolerance(order, declared_total, expected):
    """10 × 100 = 1.000 + TVA 21% = 1.210,00; se acceptă ±0,05 (I-22)."""
    invoice = validated(order, "10", declared=("1000.00", "210.00", declared_total))

    assert codes(invoice) == expected


def test_total_mismatch_message_in_romanian_format(warehouse_user):
    order = sent_order("25")
    receive(order, warehouse_user, "25")

    invoice = validated(order, "25", declared=("2600.00", "546.00", "3146.00"))

    assert codes(invoice) == ["TOTAL_MISMATCH"] * 3
    expected = "declarat (2.600,00 RON) diferă de cel calculat din linii (2.500,00 RON)"
    assert expected in messages(invoice)


# --- Antet --------------------------------------------------------------------------------


def test_order_of_another_supplier(order):
    invoice = validated(order, "10", supplier=SupplierFactory(name="Alt Furnizor SRL"))

    assert codes(invoice) == ["SUPPLIER_MISMATCH"]


def test_currency_mismatch(order):
    store_rates([PublishedRate(order.order_date, "EUR", D("5.0000"), 1)])

    invoice = validated(order, "10", currency="EUR")

    assert codes(invoice) == ["CURRENCY_MISMATCH"]
    assert "Factura este în EUR, comanda" in messages(invoice)


def test_cancelled_order():
    order = sent_order("10")
    invoice = register(order, "10")
    purchasing.cancel_order(order, "Furnizorul nu mai livrează")

    validate_invoice(invoice)

    assert codes(invoice) == ["ORDER_NOT_OPEN", "NOT_RECEIVED"]
    assert "este anulată" in messages(invoice)


def test_engine_changes_nothing(order):
    """Motorul doar citește: rularea lui de mai multe ori nu schimbă factura."""
    invoice = register(order, "12")

    assert find_problems(invoice) == find_problems(invoice)
    assert refreshed(invoice).status == Invoice.Status.REGISTERED


# --- Reverificare automată --------------------------------------------------------------------


def test_blocked_invoice_unblocks_when_goods_arrive(warehouse_user):
    """Exact situația din cerință: factura vine înaintea mărfii."""
    order = sent_order("10")
    receive(order, warehouse_user, "6")
    invoice = validated(order, "10")
    assert refreshed(invoice).status == BLOCKED

    receive(order, warehouse_user, "4")

    assert refreshed(invoice).status == MATCHED


def test_supplier_return_blocks_a_matched_invoice(order, warehouse_user):
    invoice = validated(order, "10")

    supplier_return(order.lines.get(), "2", warehouse_user)

    assert codes(invoice) == ["NOT_RECEIVED"]


def test_accepted_surplus_unblocks_the_invoice(warehouse_user, procurement_user):
    """Venit 12 pe o comandă de 10; Achizițiile acceptă surplusul (comanda crește la 12)."""
    order = sent_order("10")
    receive(order, warehouse_user, "12")
    invoice = validated(order, "12")
    assert codes(invoice) == ["NOT_RECEIVED", "OVER_ORDERED"]

    warehouse.accept_over_delivery(Discrepancy.objects.get(), procurement_user)

    assert refreshed(invoice).status == MATCHED


def test_first_come_first_served_after_a_return(order, warehouse_user):
    """5 + 5 facturate din 10, apoi retur de 1: factura mai veche rămâne potrivită, cea
    nouă se blochează. Fără oscilații: o nouă reverificare nu mai schimbă nimic."""
    older = validated(order, "5")
    newer = validated(order, "5")

    supplier_return(order.lines.get(), "1", warehouse_user)

    assert (refreshed(older).status, refreshed(newer).status) == (MATCHED, BLOCKED)
    assert recheck_order(order) == []


def test_older_invoice_validated_later_takes_priority(order):
    """Două facturi nu pot fi niciodată potrivite simultan pe aceeași marfă, indiferent
    de ordinea validării: prioritatea e ordinea înregistrării."""
    older = register(order, "10")
    newer = validated(order, "10")
    assert refreshed(newer).status == MATCHED

    validate_invoice(older)

    assert (refreshed(older).status, refreshed(newer).status) == (MATCHED, BLOCKED)


def test_approved_invoice_always_counts(order, accounting_user):
    """O factură aprobată are prioritate: decizia de plată e deja luată."""
    older = register(order, "10")
    newer = validated(order, "10")
    approve_invoice(newer, accounting_user)

    validate_invoice(older)

    assert codes(older) == ["NOT_RECEIVED", "OVER_ORDERED"]


def test_progress_shows_invoiced_quantity(order):
    validated(order, "4")
    register(order, "3")  # înregistrată, nevalidată: nu contează încă

    line = PurchaseOrderLine.objects.with_progress().get(pk=order.lines.get().pk)

    assert line.invoiced_qty == D("4")
