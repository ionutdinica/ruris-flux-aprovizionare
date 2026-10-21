"""Starea sistemului (panoul Adminului): verde, galben, roșu, pentru fiecare verificare."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.currency.bnr import PublishedRate
from apps.currency.models import RateSync
from apps.currency.services import store_rates
from apps.dashboard.health import ERROR, OK, WARNING, system_checks
from apps.notifications.models import DailyDigestRun, NotificationLog

pytestmark = pytest.mark.django_db

WEDNESDAY = datetime.date(2026, 10, 21)


def at(day, hour):
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(hour)))


def check(label, now):
    return next(c for c in system_checks(now) if c.label == label)


def rate(day):
    store_rates([PublishedRate(day, "EUR", Decimal("5.0"), 1)])


# --- Cursul BNR -------------------------------------------------------------------------------


def test_rate_never_fetched():
    assert check("Cursul BNR", at(WEDNESDAY, 10)).status == ERROR


def test_rate_up_to_date():
    rate(WEDNESDAY)

    result = check("Cursul BNR", at(WEDNESDAY, 15))

    assert result.status == OK and "21.10.2026" in result.detail


def test_rate_waiting_for_publication():
    rate(WEDNESDAY - datetime.timedelta(days=1))

    result = check("Cursul BNR", at(WEDNESDAY, 10))

    assert result.status == WARNING and "13:00" in result.detail


def test_rate_last_attempt_failed():
    rate(WEDNESDAY - datetime.timedelta(days=1))
    RateSync.objects.create(
        started_at=at(WEDNESDAY, 14),
        url="https://bnr.test/x.xml",
        success=False,
        error="BNR nu răspunde (timed out).",
    )

    result = check("Cursul BNR", at(WEDNESDAY, 15))

    assert result.status == ERROR
    assert "21.10 14:00" in result.detail  # ora României, nu UTC
    assert "timed out" in result.detail


# --- Rezumatul zilnic -------------------------------------------------------------------------


def test_digest_ran_fine():
    DailyDigestRun.objects.create(date=WEDNESDAY, sent=3, nothing_to_report=1)

    assert check("Rezumatul zilnic", at(WEDNESDAY, 9)).status == OK


def test_digest_with_failed_emails():
    DailyDigestRun.objects.create(date=WEDNESDAY, sent=2, failed=1)

    assert check("Rezumatul zilnic", at(WEDNESDAY, 9)).status == ERROR


def test_digest_missing_means_the_scheduler_is_probably_stopped():
    result = check("Rezumatul zilnic", at(WEDNESDAY, 11))

    assert result.status == ERROR and "run_scheduler" in result.detail


@pytest.mark.parametrize(
    "now",
    [at(WEDNESDAY, 7), at(WEDNESDAY + datetime.timedelta(days=3), 11)],
    ids=["devreme", "sambata"],
)
def test_digest_not_due_yet(now):
    DailyDigestRun.objects.create(date=WEDNESDAY - datetime.timedelta(days=1))

    result = check("Rezumatul zilnic", now)

    assert result.status == OK and "20.10.2026" in result.detail


# --- Emailuri eșuate și utilizatori --------------------------------------------------------------


def test_failed_emails_in_the_last_week(procurement_user):
    NotificationLog.objects.create(
        recipient=procurement_user,
        email=procurement_user.email,
        subject="x",
        body_text="x",
        status=NotificationLog.Status.FAILED,
        error="SMTPException: refuzat",
    )

    result = check("Emailuri eșuate", timezone.localtime())

    assert result.status == ERROR and "1 în ultimele 7 zile" in result.detail
    assert result.url.endswith("?status=FAILED")


def test_team_without_active_users(procurement_user, warehouse_user, accounting_user):
    assert check("Utilizatori activi", at(WEDNESDAY, 10)).status == OK

    User.objects.filter(pk=accounting_user.pk).update(is_active=False)

    result = check("Utilizatori activi", at(WEDNESDAY, 10))
    assert result.status == WARNING
    assert "Niciun utilizator activ pentru: Contabilitate" in result.detail


# --- Cine vede -------------------------------------------------------------------------------


def test_only_admin_sees_the_system_state(client, admin_user, procurement_user):
    client.force_login(admin_user)
    assert "Starea sistemului" in client.get(reverse("dashboard:home")).content.decode()

    client.force_login(procurement_user)
    assert "Starea sistemului" not in client.get(reverse("dashboard:home")).content.decode()
