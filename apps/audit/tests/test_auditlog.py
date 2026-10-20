"""Jurnalul automat al modificărilor (django-auditlog): cine, ce, când."""

import pytest
from auditlog.context import set_actor
from auditlog.models import LogEntry
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.tests.factories import TEST_PASSWORD, UserFactory

pytestmark = pytest.mark.django_db


def entries_for(obj):
    return LogEntry.objects.get_for_object(obj).order_by("timestamp", "id")


def test_creation_is_logged_with_actor(admin_user):
    with set_actor(admin_user):  # ce face middleware-ul la fiecare cerere web
        user = UserFactory(role=User.Role.WAREHOUSE)

    entry = entries_for(user).first()
    assert entry.action == LogEntry.Action.CREATE
    assert entry.actor == admin_user


def test_field_change_is_logged_with_old_and_new_value(admin_user, warehouse_user):
    with set_actor(admin_user):
        warehouse_user.role = User.Role.ACCOUNTING
        warehouse_user.save()

    entry = entries_for(warehouse_user).last()
    assert entry.action == LogEntry.Action.UPDATE
    assert entry.changes_dict["role"] == ["WAREHOUSE", "ACCOUNTING"]


def test_password_change_is_logged_but_masked(procurement_user):
    procurement_user.set_password("o-parola-noua-foarte-sigura")
    procurement_user.save()

    entry = entries_for(procurement_user).last()
    old, new = entry.changes_dict["password"]
    assert old == new == "********"  # se vede că s-a schimbat, nu și valoarea


def test_login_does_not_pollute_the_log(client, procurement_user):
    """`last_login` se schimbă la fiecare autentificare și e exclus din jurnal."""
    before = entries_for(procurement_user).count()

    client.post(
        reverse("accounts:login"),
        {"username": procurement_user.username, "password": TEST_PASSWORD},
    )

    assert entries_for(procurement_user).count() == before


def test_web_request_records_actor_and_ip(client, procurement_user):
    """Prin interfața web, middleware-ul completează automat cine și de pe ce IP."""
    client.force_login(procurement_user)

    client.post(
        reverse("accounts:password_change"),
        {
            "old_password": TEST_PASSWORD,
            "new_password1": "alta-parola-sigura-2026",
            "new_password2": "alta-parola-sigura-2026",
        },
    )

    entry = entries_for(procurement_user).last()
    assert entry.actor == procurement_user
    assert entry.remote_addr == "127.0.0.1"
    assert "password" in entry.changes_dict


def test_users_cannot_be_deleted_from_admin(client, admin_user, warehouse_user):
    client.force_login(admin_user)

    url = reverse("admin:accounts_user_delete", args=[warehouse_user.pk])
    response = client.post(url, {"post": "yes"})

    assert response.status_code == 403
    assert User.objects.filter(pk=warehouse_user.pk).exists()
