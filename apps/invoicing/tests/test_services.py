"""Fluxul de statusuri al facturii (docs/03-fluxuri-si-stari.md) și cursul valutar."""

import datetime
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from apps.audit.models import BusinessEvent
from apps.currency import services as currency
from apps.currency.bnr import PublishedRate
from apps.currency.signals import rates_synced
from apps.invoicing import services
from apps.invoicing.models import Invoice, InvoiceLine
from apps.invoicing.services import InvoiceError
from apps.warehouse.tests.scenarios import receive, sent_order

from .scenarios import codes, refreshed, register, validated

pytestmark = pytest.mark.django_db

D = Decimal
S = Invoice.Status
TODAY = timezone.localdate()


@pytest.fixture
def order(warehouse_user):
    order = sent_order("10")
    receive(order, warehouse_user, "10")
    return order


@pytest.fixture
def eur_order(warehouse_user):
    order = sent_order("10")
    order.currency = "EUR"
    order.save()
    receive(order, warehouse_user, "10")
    return order


@pytest.fixture
def clock(monkeypatch):
    """Ora „curentă” pentru regulile de curs: implicit azi, 15:00 (după publicarea BNR)."""

    class Clock:
        def set(self, hour):
            self.now = timezone.make_aware(datetime.datetime.combine(TODAY, datetime.time(hour)))

    clock = Clock()
    clock.set(15)
    monkeypatch.setattr(currency, "local_now", lambda: clock.now)
    return clock


def eur_rate(day, rate):
    currency.store_rates([PublishedRate(day, "EUR", D(rate), 1)])


def event_types(invoice):
    """Evenimentele facturii. Filtrat și pe tipul documentului: o recepție poate avea
    același id ca factura (id-urile sunt numerotate separat pe fiecare tabel)."""
    return list(
        BusinessEvent.objects.filter(
            content_type=ContentType.objects.get_for_model(Invoice), object_id=str(invoice.pk)
        )
        .order_by("id")
        .values_list("event_type", flat=True)
    )


# --- Validare și curs ----------------------------------------------------------------------


def test_ron_invoice_needs_no_rate(order):
    invoice = refreshed(validated(order, "10"))

    assert (invoice.exchange_rate, invoice.exchange_rate_date) == (D("1"), invoice.invoice_date)
    assert invoice.total_ron == D("1210.00")
    assert event_types(invoice) == ["invoice.validated"]


def test_eur_invoice_converted_at_invoice_date_rate(eur_order, clock):
    eur_rate(TODAY, "5.0905")

    invoice = refreshed(validated(eur_order, "10"))

    assert invoice.status == S.MATCHED
    assert (invoice.exchange_rate, invoice.exchange_rate_date) == (D("5.0905"), TODAY)
    assert invoice.total_ron == D("6159.51")  # 1.210,00 EUR × 5,0905 = 6.159,505 → ,51


def test_rate_is_fixed_once_set(eur_order, clock):
    """I-24: cursul salvat pe factură nu se schimbă, chiar dacă apar cursuri noi."""
    eur_rate(TODAY, "5.0905")
    invoice = validated(eur_order, "10")
    currency.store_rates([PublishedRate(TODAY, "USD", D("4.3"), 1)])
    services.recheck_order(eur_order)

    assert refreshed(invoice).exchange_rate == D("5.0905")


def test_waits_for_todays_rate_then_resumes_automatically(eur_order, clock):
    """I-26: factura de azi, validată dimineața, înainte ca BNR să publice."""
    eur_rate(TODAY - datetime.timedelta(days=1), "5.0800")
    clock.set(10)

    invoice = validated(eur_order, "10")
    assert refreshed(invoice).status == S.RATE_PENDING
    assert refreshed(invoice).total_ron is None

    clock.set(13)
    eur_rate(TODAY, "5.0905")  # job-ul BNR a adus cursul și anunță
    rates_synced.send(sender=None, syncs=[])

    invoice = refreshed(invoice)
    assert (invoice.status, invoice.exchange_rate) == (S.MATCHED, D("5.0905"))
    assert event_types(invoice) == ["invoice.validated", "invoice.rechecked"]


def test_pending_invoice_stays_pending_while_rate_unknown(eur_order, clock):
    clock.set(10)
    invoice = validated(eur_order, "10")

    assert services.resume_rate_pending() == []
    assert refreshed(invoice).status == S.RATE_PENDING


def test_future_invoice_date_is_refused(order):
    invoice = register(order, "10", invoice_date=TODAY + datetime.timedelta(days=1))

    with pytest.raises(InvoiceError, match="viitor"):
        services.validate_invoice(invoice)


def test_invoice_without_lines_is_refused(order):
    invoice = register(order, "10")
    InvoiceLine.objects.filter(invoice=invoice).delete()

    with pytest.raises(InvoiceError, match="nicio linie"):
        services.validate_invoice(invoice)


def test_cannot_validate_twice(order):
    invoice = validated(order, "10")

    with pytest.raises(InvoiceError):
        services.validate_invoice(invoice)


# --- Corectare ---------------------------------------------------------------------------


def test_reopen_correct_and_revalidate(order):
    """O greșeală de tastare (12 în loc de 10): redeschidere, corectare, revalidare."""
    invoice = validated(order, "12")
    assert refreshed(invoice).status == S.BLOCKED

    services.reopen_invoice(invoice)
    invoice = refreshed(invoice)
    assert (invoice.status, invoice.exchange_rate, invoice.problems) == (S.REGISTERED, None, [])

    InvoiceLine.objects.filter(invoice=invoice).update(quantity=D("10"))
    invoice.declared_net, invoice.declared_vat, invoice.declared_total = (
        D("1000"),
        D("210"),
        D("1210"),
    )
    invoice.save()
    services.validate_invoice(invoice)

    assert refreshed(invoice).status == S.MATCHED


def test_matched_invoice_cannot_be_reopened(order):
    with pytest.raises(InvoiceError):
        services.reopen_invoice(validated(order, "10"))


# --- Aprobare, forțare, plată ---------------------------------------------------------------


def test_approve_matched(order, accounting_user):
    invoice = services.approve_invoice(validated(order, "10"), accounting_user)

    assert (invoice.status, invoice.approved_by) == (S.APPROVED, accounting_user)
    assert invoice.approved_at is not None


def test_blocked_invoice_cannot_simply_be_approved(order, accounting_user):
    with pytest.raises(InvoiceError, match="potrivită"):
        services.approve_invoice(validated(order, "12"), accounting_user)


def test_approval_rechecks_at_the_last_moment(order, accounting_user):
    """Dacă datele s-au schimbat pe lângă reguli, aprobarea nu trece pe un rezultat vechi."""
    invoice = validated(order, "10")
    InvoiceLine.objects.filter(invoice=invoice).update(unit_price=D("150"))

    with pytest.raises(InvoiceError, match="nu mai corespunde"):
        services.approve_invoice(invoice, accounting_user)
    assert refreshed(invoice).status == S.MATCHED


def test_force_approve_requires_a_reason(order, accounting_user):
    invoice = validated(order, "12")

    with pytest.raises(InvoiceError, match="obligatorie"):
        services.force_approve_invoice(invoice, accounting_user, "   ")
    assert refreshed(invoice).status == S.BLOCKED


def test_force_approve_keeps_what_was_ignored(order, accounting_user):
    invoice = validated(order, "12")

    services.force_approve_invoice(invoice, accounting_user, "Acord telefonic cu furnizorul")

    invoice = refreshed(invoice)
    assert (invoice.status, invoice.override_reason) == (
        S.APPROVED,
        "Acord telefonic cu furnizorul",
    )
    event = BusinessEvent.objects.get(event_type="invoice.force_approved")
    assert event.data["justificare"] == "Acord telefonic cu furnizorul"
    assert "nesosite" in event.data["motive"][0]


def test_only_blocked_invoices_can_be_forced(order, accounting_user):
    with pytest.raises(InvoiceError):
        services.force_approve_invoice(validated(order, "10"), accounting_user, "motiv")


def test_mark_paid(order, accounting_user):
    invoice = services.approve_invoice(validated(order, "10"), accounting_user)

    invoice = services.mark_paid(invoice, TODAY, "OP 1234")

    assert (invoice.status, invoice.paid_at, invoice.payment_reference) == (
        S.PAID,
        TODAY,
        "OP 1234",
    )


@pytest.mark.parametrize(("days", "message"), [(1, "viitor"), (-1, "înaintea datei")])
def test_payment_date_checks(order, accounting_user, days, message):
    invoice = services.approve_invoice(validated(order, "10"), accounting_user)

    with pytest.raises(InvoiceError, match=message):
        services.mark_paid(invoice, TODAY + datetime.timedelta(days=days))


def test_only_approved_invoices_can_be_paid(order):
    with pytest.raises(InvoiceError):
        services.mark_paid(validated(order, "10"), TODAY)


def test_paid_invoice_is_not_rechecked(order, accounting_user, warehouse_user):
    """O factură plătită rămâne plătită, chiar dacă ulterior apare un retur."""
    invoice = services.mark_paid(
        services.approve_invoice(validated(order, "10"), accounting_user), TODAY
    )
    line = order.lines.get()
    from apps.warehouse import services as warehouse

    warehouse.record_stock_movement(
        line.product, "SUPPLIER_RETURN", D("2"), warehouse_user, "Defect", order_line=line
    )

    assert refreshed(invoice).status == S.PAID


# --- Respingere ----------------------------------------------------------------------------


def test_reject_blocked_invoice(order):
    invoice = services.reject_invoice(validated(order, "12"), "Cantitate greșită, cerem storno")

    assert (invoice.status, invoice.rejection_reason) == (
        S.REJECTED,
        "Cantitate greșită, cerem storno",
    )


def test_reject_requires_reason(order):
    with pytest.raises(InvoiceError, match="obligatoriu"):
        services.reject_invoice(validated(order, "12"), "")


def test_matched_invoice_cannot_be_rejected(order):
    with pytest.raises(InvoiceError):
        services.reject_invoice(validated(order, "10"), "motiv")


def test_rejected_invoice_no_longer_counts(order):
    first = validated(order, "12")
    services.reject_invoice(first, "Greșită")

    assert refreshed(validated(order, "10")).status == S.MATCHED


# --- Validări de introducere ------------------------------------------------------------------


def test_same_supplier_invoice_number_twice_is_impossible(order):
    """I-21: protecția la dublă introducere e garantată de baza de date."""
    invoice = register(order, "10")

    with pytest.raises(IntegrityError):
        Invoice.objects.create(
            supplier=invoice.supplier,
            supplier_invoice_number=invoice.supplier_invoice_number,
            invoice_date=TODAY,
            due_date=TODAY,
            currency="RON",
            declared_net=0,
            declared_vat=0,
            declared_total=0,
        )


def test_date_validations(order):
    invoice = register(order, "10")
    invoice.invoice_date = TODAY + datetime.timedelta(days=1)
    invoice.due_date = TODAY

    with pytest.raises(ValidationError) as error:
        invoice.full_clean()

    assert set(error.value.message_dict) == {"invoice_date", "due_date"}


def test_internal_numbers_follow_registration_order(order):
    first, second = register(order, "1"), register(order, "1")

    year = TODAY.year
    assert (first.number, second.number) == (f"FAC-{year}-0001", f"FAC-{year}-0002")


def test_status_changes_are_in_the_invoice_history(order):
    from auditlog.models import LogEntry

    invoice = validated(order, "12")

    changes = [
        entry.changes_dict.get("status")
        for entry in LogEntry.objects.get_for_object(invoice)
        if "status" in entry.changes_dict
    ]
    assert ["REGISTERED", "BLOCKED"] in changes
    assert codes(invoice) == ["NOT_RECEIVED", "OVER_ORDERED"]


def test_status_changed_at_moves_only_when_the_status_changes(order, warehouse_user):
    """„De când e blocată” nu se resetează la fiecare reverificare automată."""
    invoice = validated(order, "12")
    blocked_since = refreshed(invoice).status_changed_at

    services.recheck_order(order)  # reverificare: tot blocată
    assert refreshed(invoice).status_changed_at == blocked_since

    services.reopen_invoice(invoice)  # alt status
    assert refreshed(invoice).status_changed_at > blocked_since
