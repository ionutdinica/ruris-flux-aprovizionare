"""Rezumatele simulate de datele demo și marcarea lor în Mailpit."""

import datetime
import io
import json

import pytest
from django.utils import timezone

from apps.demo import mailpit
from apps.demo.seed import DemoSeeder

WEDNESDAY = datetime.date(2026, 10, 21)


def at(day, hour):
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(hour)))


def planned_days(now):
    seeder = DemoSeeder("x" * 12, now=now)
    seeder.plan_daily_digests()
    return sorted(timezone.localtime(when).date() for when, *_ in seeder.agenda), seeder


def test_after_eight_today_is_simulated_too():
    days, seeder = planned_days(at(WEDNESDAY, 18))

    assert seeder.digest_today
    assert days == [
        datetime.date(2026, 10, d) for d in (16, 19, 20, 21)
    ]  # vineri, luni, marți, azi


@pytest.mark.parametrize(
    "now", [at(WEDNESDAY, 7), at(datetime.date(2026, 10, 24), 18)], ids=["dimineata", "sambata"]
)
def test_before_eight_or_at_the_weekend_today_is_left_to_the_scheduler(now):
    days, seeder = planned_days(now)

    assert not seeder.digest_today and len(days) == 3 and now.date() not in days


def test_digests_go_out_at_the_usual_hour():
    seeder = DemoSeeder("x" * 12, now=at(WEDNESDAY, 18))
    seeder.plan_daily_digests()

    assert {timezone.localtime(when).strftime("%H:%M") for when, *_ in seeder.agenda} == {"08:05"}


# --- Mailpit -----------------------------------------------------------------------------------


class FakeMailpit:
    def __init__(self, messages):
        self.messages = messages
        self.marked = None

    def urlopen(self, request, timeout):
        if isinstance(request, str):  # GET lista
            return io.BytesIO(json.dumps({"messages": self.messages}).encode())
        self.marked = json.loads(request.data)  # PUT marcarea
        return io.BytesIO(b"{}")


def email(id_, created, read=False):
    return {"ID": id_, "Created": created, "Read": read}


def test_only_unread_emails_from_past_days_are_marked(monkeypatch, settings):
    settings.MAILPIT_API_URL = "http://mailpit.test:8025"
    fake = FakeMailpit(
        [
            email("ieri", "2026-10-20T05:05:00Z"),
            email("azi", "2026-10-21T05:05:00Z"),
            email("deja-citit", "2026-10-19T05:05:00Z", read=True),
            email("ieri-seara-tarziu", "2026-10-20T21:30:00Z"),  # 00:30 azi, ora României
        ]
    )
    monkeypatch.setattr(mailpit, "urlopen", fake.urlopen)

    assert mailpit.mark_past_emails_read(WEDNESDAY) == 1
    assert fake.marked == {"IDs": ["ieri"], "Read": True}


def test_nothing_happens_without_mailpit(settings):
    settings.MAILPIT_API_URL = ""

    assert mailpit.mark_past_emails_read(WEDNESDAY) is None


def test_unreachable_mailpit_is_a_clear_error(monkeypatch, settings):
    settings.MAILPIT_API_URL = "http://mailpit.test:8025"

    def offline(request, timeout):
        raise OSError("Connection refused")

    monkeypatch.setattr(mailpit, "urlopen", offline)

    with pytest.raises(mailpit.MailpitError, match="Connection refused"):
        mailpit.mark_past_emails_read(WEDNESDAY)
