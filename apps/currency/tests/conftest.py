"""Unelte pentru testele de curs: un BNR fals (fișiere locale) și un ceas fixat."""

import datetime
from pathlib import Path

import pytest
from django.utils import timezone

from apps.currency import bnr, services

DATA = Path(__file__).parent / "data"


def at(text):
    """„2026-10-21 10:00” → moment în fusul orar al aplicației (București)."""
    return timezone.make_aware(datetime.datetime.fromisoformat(text))


def day(text):
    return datetime.date.fromisoformat(text)


def load(name, *, until=None):
    """Salvează direct cursurile dintr-un fișier de test (opțional, doar până la o dată)."""
    rates = bnr.parse_rates((DATA / name).read_bytes())
    if until:
        rates = [r for r in rates if r.date <= day(until)]
    return services.store_rates(rates)


@pytest.fixture
def clock(monkeypatch):
    """Ora „curentă” a aplicației. Implicit: miercuri 21.10.2026, 10:00, adică
    înainte ca BNR să publice cursul zilei (ultimul curs din fișiere: 20.10)."""

    class Clock:
        def set(self, text):
            self.now = at(text)

    clock = Clock()
    clock.set("2026-10-21 10:00")
    monkeypatch.setattr(services, "local_now", lambda: clock.now)
    return clock


@pytest.fixture
def fake_bnr(monkeypatch, settings):
    """Înlocuiește descărcarea: adresele BNR primesc fișierele din tests/data."""
    settings.BNR_BASE_URL = "https://bnr.test"

    class FakeBnr:
        down = False  # True = BNR nu răspunde
        calls = []

        def download(self, url):
            self.calls.append(url)
            if self.down:
                raise bnr.BnrError("BNR nu răspunde (timed out).")
            files = {
                bnr.recent_url(): "recent.xml",
                bnr.year_url(2025): "year2025.xml",
                bnr.year_url(2026): "year2026.xml",
            }
            if url not in files:
                raise bnr.BnrError(f"BNR nu răspunde (HTTP 404 pentru {url}).")
            return (DATA / files[url]).read_bytes()

    fake = FakeBnr()
    fake.calls = []
    monkeypatch.setattr(bnr, "download", fake.download)
    return fake
