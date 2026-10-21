"""Fundația datelor demo: mașina timpului, echipa, catalogul, protecțiile comenzii."""

import datetime
from io import StringIO

import pytest
from auditlog.models import LogEntry
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import BusinessEvent
from apps.audit.services import record_event
from apps.catalog.models import Product, Supplier
from apps.catalog.tests.factories import SupplierFactory
from apps.core.validators import validate_cui
from apps.demo.catalog import PRODUCTS, SUPPLIERS, TEAM
from apps.demo.clock import travel_to
from apps.demo.seed import DemoSeeder, acting_as, moment
from apps.invoicing.models import Invoice

pytestmark = pytest.mark.django_db

PAST = timezone.make_aware(datetime.datetime(2026, 6, 15, 10, 30))


# --- Mașina timpului ---------------------------------------------------------------------------


def test_clock_and_dates_move():
    with travel_to(PAST):
        assert timezone.now() == PAST
        assert timezone.localdate() == datetime.date(2026, 6, 15)

    assert timezone.now() > PAST  # înapoi în prezent


def test_auto_dates_and_stubborn_defaults_move_too(procurement_user):
    """auto_now_add, jurnalul django-auditlog și Invoice.status_changed_at (default=now)."""
    # Valorile implicite folosite o dată înainte: Django le memorează (cache) la prima
    # folosire, iar mașina timpului trebuie să le mute totuși.
    LogEntry._meta.get_field("timestamp").get_default()
    Invoice._meta.get_field("status_changed_at").get_default()
    with travel_to(PAST):
        supplier = SupplierFactory()  # created_at (auto_now_add) + LogEntry (default=now)
        event = record_event(BusinessEvent.Type.LOGIN, "test", actor=procurement_user)
        status_default = Invoice._meta.get_field("status_changed_at").get_default()

    assert supplier.created_at == PAST
    assert LogEntry.objects.get_for_object(supplier).get().timestamp == PAST
    assert event.timestamp == PAST
    assert status_default == PAST
    assert Invoice._meta.get_field("status_changed_at").get_default() > PAST  # restaurat


def test_clock_is_restored_even_after_an_error():
    with pytest.raises(RuntimeError), travel_to(PAST):
        raise RuntimeError("o eroare în mijlocul generării datelor demo")

    assert timezone.now() > PAST
    assert LogEntry._meta.get_field("timestamp").get_default() > PAST


def test_naive_moments_are_refused():
    with pytest.raises(ValueError, match="fus orar"), travel_to(datetime.datetime(2026, 6, 15)):
        pass


def test_acting_as_signs_both_audit_logs(procurement_user):
    with acting_as(procurement_user):
        supplier = SupplierFactory()
        event = record_event(BusinessEvent.Type.ORDER_SENT, "test")

    assert LogEntry.objects.get_for_object(supplier).get().actor == procurement_user
    assert event.actor == procurement_user


# --- Echipa și catalogul -----------------------------------------------------------------------


def test_base_data(settings):
    seeder = DemoSeeder("parola-demo-123", today=datetime.date(2026, 10, 21))

    seeder.create_base_data()

    assert User.objects.count() == len(TEAM)
    assert {u.role for u in User.objects.all()} == set(User.Role)
    admin = User.objects.get(username="andrei.ionescu")
    assert admin.is_staff and admin.is_superuser and admin.check_password("parola-demo-123")
    assert Supplier.objects.count() == len(SUPPLIERS)
    assert Product.objects.count() == len(PRODUCTS)


def test_romanian_tax_ids_are_valid():
    DemoSeeder("x" * 12).create_base_data()

    for supplier in Supplier.objects.filter(country="RO"):
        validate_cui(supplier.tax_id)  # ar ridica ValidationError


def test_base_data_is_dated_before_the_activity():
    today = datetime.date(2026, 10, 21)
    DemoSeeder("x" * 12, today=today).create_base_data()

    supplier = Supplier.objects.first()
    assert supplier.created_at.date() < today - datetime.timedelta(days=100)
    entry = LogEntry.objects.get_for_object(supplier).get()
    assert entry.actor.username == "andrei.ionescu"  # adăugat de administrator


def test_moment_is_local_time():
    assert timezone.localtime(moment(datetime.date(2026, 10, 21), 8)).hour == 8


# --- Comanda și protecțiile --------------------------------------------------------------------


@pytest.fixture(autouse=True)
def base_data_only(request, monkeypatch):
    """Testele comenzii verifică protecțiile și parola, nu povestea (testată separat, în
    test_scenarios.py): generatorul creează aici doar echipa și catalogul."""
    if "allow_full_seed" not in request.keywords:

        def run(self):
            self.create_base_data()
            return ["doar datele de bază"]

        monkeypatch.setattr(DemoSeeder, "run", run)


def run(*args):
    out = StringIO()
    call_command("seed_demo", *args, stdout=out)
    return out.getvalue()


def test_command_on_an_empty_database_prints_the_accounts():
    output = run("--password", "parola-demo-123")

    assert "maria.pop" in output and "Achiziții" in output
    assert "parola-demo-123" not in output  # parola dată nu se repetă pe ecran


def test_generated_password_is_shown_once():
    output = run()

    password = output.split("Parola generată: ")[1].split()[0]
    assert User.objects.get(username="maria.pop").check_password(password)


def test_refuses_to_mix_with_existing_data(procurement_user):
    with pytest.raises(CommandError, match="conține deja date"):
        run()


def test_reset_needs_explicit_permission(settings, procurement_user):
    settings.DEMO_RESET_ALLOWED = False

    with pytest.raises(CommandError, match="DEMO_RESET_ALLOWED"):
        run("--reset")
    assert User.objects.filter(pk=procurement_user.pk).exists()  # nimic șters


@pytest.mark.django_db(transaction=True)  # „flush” nu poate rula într-o tranzacție deschisă
def test_reset_when_allowed(settings, procurement_user):
    settings.DEMO_RESET_ALLOWED = True

    run("--reset", "--password", "parola-demo-123")

    assert not User.objects.filter(pk=procurement_user.pk).exists()
    assert User.objects.filter(username="maria.pop").exists()


@pytest.mark.allow_full_seed
def test_bnr_unavailable_skips_eur_invoices_instead_of_inventing_rates(monkeypatch):
    """Fără internet / BNR: facturile în EUR nu primesc un curs inventat (I-28)."""
    monkeypatch.setattr("apps.demo.seed.currency.sync_rates", lambda force: [])

    log = DemoSeeder("parola-demo-123").run()

    assert "BNR indisponibil" in log[0]
    assert not Invoice.objects.filter(currency="EUR").exists()
    assert Invoice.objects.filter(currency="RON").exists()  # restul demo-ului e complet
