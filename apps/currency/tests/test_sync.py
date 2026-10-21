"""Actualizarea cursurilor de la BNR: ce, când și cât se descarcă; ce se întâmplă la erori."""

import pytest

from apps.currency import bnr
from apps.currency.models import ExchangeRate, RateSync
from apps.currency.services import get_rate, needs_sync, store_rates, sync_rates
from apps.currency.signals import rates_synced

from .conftest import DATA, day, load

pytestmark = pytest.mark.django_db


@pytest.fixture
def received_signals():
    calls = []

    def receiver(sender, syncs, **kwargs):
        calls.append(syncs)

    rates_synced.connect(receiver)
    yield calls
    rates_synced.disconnect(receiver)


def test_first_run_loads_two_years_of_history(clock, fake_bnr, received_signals):
    syncs = sync_rates()

    assert fake_bnr.calls == [bnr.year_url(2025), bnr.year_url(2026), bnr.recent_url()]
    assert [s.success for s in syncs] == [True, True, True]
    assert ExchangeRate.objects.filter(date="2025-12-24", currency="EUR").exists()
    assert len(received_signals) == 1  # o singură notificare, la final


def test_same_rates_are_not_stored_twice(clock):
    content = (DATA / "recent.xml").read_bytes()

    assert store_rates(bnr.parse_rates(content)) == 21
    assert store_rates(bnr.parse_rates(content)) == 0
    assert ExchangeRate.objects.count() == 21


def test_nothing_to_download_before_publication(clock, fake_bnr):
    """Miercuri, 10:00: avem cursul de marți, iar cel de azi nu e publicat încă."""
    load("recent.xml")

    assert not needs_sync()
    assert sync_rates() == []
    assert fake_bnr.calls == []


def test_after_publication_only_the_recent_file_is_downloaded(clock, fake_bnr):
    load("recent.xml")
    clock.set("2026-10-21 13:15")

    sync_rates()

    assert fake_bnr.calls == [bnr.recent_url()]


def test_holiday_one_check_after_deadline_then_quiet(clock, fake_bnr):
    """Fișierul BNR nu are curs pentru 21.10 (să zicem sărbătoare): job-ul întreabă până
    la ora-limită, apoi ziua devine „cunoscută” și nu mai descarcă nimic."""
    load("recent.xml")

    clock.set("2026-10-21 13:30")
    sync_rates()
    assert needs_sync()  # încă nu putem ști dacă BNR doar întârzie

    clock.set("2026-10-21 14:10")
    sync_rates()
    assert not needs_sync()
    assert get_rate("EUR", day("2026-10-21")).date == day("2026-10-20")

    clock.set("2026-10-21 16:00")
    assert sync_rates() == []
    assert len(fake_bnr.calls) == 2


def test_bnr_down_is_recorded_and_retried(clock, fake_bnr, received_signals):
    load("recent.xml", until="2026-10-16")
    clock.set("2026-10-20 15:00")
    fake_bnr.down = True

    [failed] = sync_rates()

    assert not failed.success and "nu răspunde" in failed.error
    assert received_signals == []
    assert needs_sync()  # data viitoare se reîncearcă

    fake_bnr.down = False
    [ok] = sync_rates()

    assert ok.success and ok.rates_created == 6  # 19 și 20.10 × 3 monede
    assert len(received_signals) == 1


def test_long_pause_fills_the_gap_from_yearly_archives(clock, fake_bnr):
    """Ultimul curs știut e din decembrie: fișierul zilnic (10 zile) nu ar acoperi golul."""
    load("year2025.xml")
    clock.set("2026-10-21 14:00")

    sync_rates()

    assert fake_bnr.calls == [bnr.year_url(2025), bnr.year_url(2026), bnr.recent_url()]


def test_stops_at_first_error(clock, fake_bnr, settings):
    """Dacă arhiva anuală nu poate fi adusă, nu continuăm cu fișierul recent: altfel
    istoricul ar rămâne cu un gol care ar părea o perioadă fără publicări."""
    load("year2025.xml")
    clock.set("2027-02-01 14:00")  # arhiva 2027 nu există în BNR-ul de test

    syncs = sync_rates()

    assert [s.success for s in syncs] == [True, True, False]
    assert bnr.recent_url() not in fake_bnr.calls


def test_force_downloads_even_when_up_to_date(clock, fake_bnr, admin_user):
    load("recent.xml")

    [sync] = sync_rates(force=True, user=admin_user)

    assert sync.triggered_by == admin_user
    assert RateSync.objects.get() == sync
