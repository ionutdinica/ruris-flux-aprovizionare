"""Trimiterea: când, cui, o dată pe zi, ce se întâmplă când serverul de email nu răspunde."""

import datetime
from io import StringIO
from smtplib import SMTPException

import pytest
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.models import User
from apps.core.management.commands import run_scheduler
from apps.notifications import services
from apps.notifications.models import DailyDigestRun, NotificationLog
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.warehouse.tests.scenarios import sent_order

pytestmark = pytest.mark.django_db

WEDNESDAY = datetime.date(2026, 10, 21)


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(hour, minute)))


@pytest.fixture
def clock(monkeypatch):
    """Ora „curentă” a notificărilor. Implicit: miercuri, 08:00."""

    class Clock:
        def set(self, when):
            self.now = when

    clock = Clock()
    clock.set(at(WEDNESDAY, 8))
    monkeypatch.setattr(services, "local_now", lambda: clock.now)
    return clock


@pytest.fixture
def late_order(procurement_user, warehouse_user):
    """O comandă a Mariei, cu termenul depășit: o primesc ea și Depozitul."""
    order = sent_order("10")
    PurchaseOrder.objects.filter(pk=order.pk).update(owner=procurement_user)
    PurchaseOrderLine.objects.filter(order=order).update(
        expected_date=WEDNESDAY - datetime.timedelta(days=2)
    )
    return order


def run(clock_time=None):
    return services.send_daily_digests(now=clock_time)


def recipients():
    return sorted(address for message in mail.outbox for address in message.to)


# --- Cui și ce ----------------------------------------------------------------------------------


def test_each_person_gets_only_their_problems(
    clock, late_order, procurement_user, warehouse_user, accounting_user, admin_user
):
    logs = run(clock.now)

    assert recipients() == sorted([procurement_user.email, warehouse_user.email])
    assert accounting_user.email not in recipients()  # nimic de rezolvat → niciun email
    assert admin_user.email not in recipients()  # Administratorul nu primește rezumat
    assert {log.status for log in logs} == {NotificationLog.Status.SENT}
    run_record = DailyDigestRun.objects.get(date=WEDNESDAY)
    others = services.digest_recipients().count() - 2  # restul: nimic de rezolvat
    assert (run_record.sent, run_record.failed, run_record.nothing_to_report) == (2, 0, others)


def test_email_has_html_and_text_and_comes_from_the_app(clock, late_order, settings):
    run(clock.now)

    message = next(m for m in mail.outbox if m.subject.startswith("Aprovizionare"))
    assert isinstance(message, EmailMultiAlternatives)
    assert message.from_email == settings.DEFAULT_FROM_EMAIL
    assert message.alternatives[0][1] == "text/html"
    assert late_order.number in message.body


def test_log_keeps_what_was_sent(clock, late_order, procurement_user):
    run(clock.now)

    log = NotificationLog.objects.get(recipient=procurement_user)
    assert log.items == [f"ORDER_LATE:{late_order.pk}"]
    assert log.email == procurement_user.email and log.kind == NotificationLog.Kind.DAILY


# --- Când ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "when",
    [at(WEDNESDAY, 7, 59), at(WEDNESDAY + datetime.timedelta(days=3), 9)],  # prea devreme; sâmbătă
    ids=["inainte-de-ora-8", "sambata"],
)
def test_not_before_the_hour_nor_at_the_weekend(late_order, when):
    assert run(when) == []
    assert mail.outbox == []


def test_once_a_day_even_if_the_job_runs_every_10_minutes(clock, late_order):
    run(at(WEDNESDAY, 8))
    run(at(WEDNESDAY, 8, 10))
    run(at(WEDNESDAY, 15))

    assert len(mail.outbox) == 2  # Maria și Depozitul, câte o dată


def test_late_start_still_sends_that_day(late_order):
    """Serverul a fost oprit la 08:00: rezumatul pleacă la prima rulare de după."""
    run(at(WEDNESDAY, 11, 40))

    assert len(mail.outbox) == 2


def test_problem_appearing_during_the_day_waits_for_tomorrow(clock, accounting_user, late_order):
    run(at(WEDNESDAY, 8))
    mail.outbox.clear()
    accounting_user.role = User.Role.WAREHOUSE  # devine destinatar al comenzii întârziate
    accounting_user.save()

    run(at(WEDNESDAY, 12))

    assert mail.outbox == []


def test_unsolved_problem_is_repeated_next_day_without_new_mark(clock, late_order):
    run(at(WEDNESDAY, 8))
    first = mail.outbox[0]
    mail.outbox.clear()

    run(at(WEDNESDAY + datetime.timedelta(days=1), 8))

    assert len(mail.outbox) == 2
    assert "[NOU]" in first.body
    assert "[NOU]" not in mail.outbox[0].body  # aceeași problemă: reamintită, dar nu „nouă”


# --- Erori de trimitere ---------------------------------------------------------------------------


@pytest.fixture
def smtp_rejects(monkeypatch):
    """Serverul de email refuză adresele din `rejected`; restul trec."""
    rejected = set()
    original = EmailMultiAlternatives.send

    def send(self, fail_silently=False):
        if set(self.to) & rejected:
            raise SMTPException("Connection unexpectedly closed")
        return original(self, fail_silently)

    monkeypatch.setattr(EmailMultiAlternatives, "send", send)
    return rejected


def test_failure_is_logged_and_does_not_stop_the_others(
    clock, late_order, procurement_user, warehouse_user, smtp_rejects
):
    smtp_rejects.add(procurement_user.email)

    run(clock.now)

    failed = NotificationLog.objects.get(recipient=procurement_user)
    assert failed.status == NotificationLog.Status.FAILED
    assert "SMTPException: Connection unexpectedly closed" == failed.error
    assert recipients() == [warehouse_user.email]


def test_failed_email_is_retried_at_most_three_times(
    clock, late_order, procurement_user, smtp_rejects
):
    smtp_rejects.add(procurement_user.email)
    for minute in (0, 10, 20, 30, 40):
        run(at(WEDNESDAY, 8, minute))

    attempts = NotificationLog.objects.filter(recipient=procurement_user)
    assert attempts.count() == services.MAX_DAILY_ATTEMPTS


def test_retry_succeeds_when_the_server_is_back(clock, late_order, procurement_user, smtp_rejects):
    smtp_rejects.add(procurement_user.email)
    run(at(WEDNESDAY, 8))
    smtp_rejects.clear()

    run(at(WEDNESDAY, 8, 10))

    statuses = list(
        NotificationLog.objects.filter(recipient=procurement_user)
        .order_by("id")
        .values_list("status", flat=True)
    )
    assert statuses == ["FAILED", "SENT"]
    run_record = DailyDigestRun.objects.get(date=WEDNESDAY)
    assert (run_record.sent, run_record.failed) == (2, 0)


# --- Comanda și planificatorul -------------------------------------------------------------------


def test_command_now_sends_even_on_saturday(clock, late_order):
    clock.set(at(WEDNESDAY + datetime.timedelta(days=3), 9))
    out = StringIO()

    call_command("send_notifications", "--now", stdout=out)

    assert "Trimis →" in out.getvalue()
    assert NotificationLog.objects.filter(kind=NotificationLog.Kind.MANUAL).count() == 2


def test_command_says_when_there_is_nothing_to_send(clock):
    out = StringIO()

    call_command("send_notifications", stdout=out)

    assert "Nimic de trimis" in out.getvalue()


def test_scheduler_runs_the_notifications():
    assert "send_notifications" in run_scheduler.JOBS


def test_a_failed_email_does_not_count_as_seen(clock, late_order, procurement_user, smtp_rejects):
    """Omul nu a primit emailul eșuat, deci problemele rămân „NOU” la reîncercare."""
    smtp_rejects.add(procurement_user.email)
    run(at(WEDNESDAY, 8))
    smtp_rejects.clear()

    run(at(WEDNESDAY, 8, 10))

    delivered = next(m for m in mail.outbox if m.to == [procurement_user.email])
    assert "[NOU]" in delivered.body
