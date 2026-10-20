"""Evenimentele de business: înregistrare, context și imposibilitatea modificării."""

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import TEST_PASSWORD
from apps.audit.context import audit_context
from apps.audit.models import BusinessEvent, ImmutableRecordError
from apps.audit.services import record_event

pytestmark = pytest.mark.django_db

T = BusinessEvent.Type


# --- record_event ---------------------------------------------------------------


def test_record_event_with_target_and_details(admin_user, warehouse_user):
    event = record_event(
        T.LOGIN,
        "Mesaj de test",
        actor=admin_user,
        target=warehouse_user,  # orice model poate fi „documentul” evenimentului
        data={"justificare": "test"},
    )

    event.refresh_from_db()
    assert event.actor == admin_user
    assert event.target == warehouse_user
    assert event.object_repr == str(warehouse_user)
    assert event.data == {"justificare": "test"}


def test_actor_and_ip_come_from_request_context(procurement_user):
    with audit_context(actor=procurement_user, remote_addr="10.0.0.7"):
        event = record_event(T.LOGOUT, "Mesaj")

    assert event.actor == procurement_user
    assert event.remote_addr == "10.0.0.7"


def test_outside_a_request_actor_is_empty(db):
    """Ex. un job programat: nu există utilizator care să fi făcut acțiunea."""
    event = record_event(T.LOGOUT, "Mesaj")

    assert event.actor is None


def test_context_does_not_leak_after_a_request(client, procurement_user):
    """După o cerere web, contextul e golit: un job rulat ulterior pe același
    fir de execuție nu „moștenește” utilizatorul cererii (bug găsit de teste)."""
    client.force_login(procurement_user)
    client.get(reverse("dashboard:home"))

    event = record_event(T.LOGOUT, "Eveniment din afara cererii")

    assert event.actor is None
    assert event.remote_addr is None


def test_forwarded_ip_behind_proxy(rf):
    from apps.audit.context import client_ip

    request = rf.get("/", HTTP_X_FORWARDED_FOR="203.0.113.5, 10.0.0.1")

    assert client_ip(request) == "203.0.113.5"


def test_unknown_event_type_is_rejected(db):
    with pytest.raises(ValueError):
        record_event("factura.inventata", "Mesaj")


# --- Append-only: nimic nu se modifică, nimic nu se șterge ----------------------


@pytest.fixture
def event(db):
    return record_event(T.LOGIN, "Mesaj original")


def test_event_cannot_be_modified(event):
    event.message = "Mesaj falsificat"

    with pytest.raises(ImmutableRecordError):
        event.save()


def test_event_cannot_be_deleted(event):
    with pytest.raises(ImmutableRecordError):
        event.delete()


def test_bulk_update_and_delete_are_blocked(event):
    with pytest.raises(ImmutableRecordError):
        BusinessEvent.objects.update(message="Mesaj falsificat")
    with pytest.raises(ImmutableRecordError):
        BusinessEvent.objects.all().delete()

    event.refresh_from_db()
    assert event.message == "Mesaj original"


def test_admin_is_read_only(client, admin_user, event):
    client.force_login(admin_user)

    assert client.get(reverse("admin:audit_businessevent_add")).status_code == 403
    delete_url = reverse("admin:audit_businessevent_delete", args=[event.pk])
    assert client.post(delete_url, {"post": "yes"}).status_code == 403


# --- Autentificări în jurnal ------------------------------------------------------


def test_successful_login_is_recorded(client, procurement_user):
    client.post(
        reverse("accounts:login"),
        {"username": procurement_user.username, "password": TEST_PASSWORD},
    )

    event = BusinessEvent.objects.get(event_type=T.LOGIN)
    assert event.actor == procurement_user
    assert event.remote_addr == "127.0.0.1"


def test_failed_login_is_recorded_without_password(client, procurement_user):
    client.post(
        reverse("accounts:login"),
        {"username": procurement_user.username, "password": "parola-gresita"},
    )

    event = BusinessEvent.objects.get(event_type=T.LOGIN_FAILED)
    assert event.actor is None
    assert event.data == {"utilizator": procurement_user.username}
    assert "parola-gresita" not in str(event.data) + event.message


def test_logout_is_recorded(client, procurement_user):
    client.force_login(procurement_user)

    client.post(reverse("accounts:logout"))

    assert BusinessEvent.objects.get(event_type=T.LOGOUT).actor == procurement_user
