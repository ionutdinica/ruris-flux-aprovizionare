"""Comenzile rulate de job: fetch_bnr_rates și planificatorul run_scheduler."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.core.management.commands import run_scheduler
from apps.currency import bnr
from apps.currency.models import ExchangeRate

from .conftest import load

pytestmark = pytest.mark.django_db


def run(*args):
    out = StringIO()
    call_command("fetch_bnr_rates", *args, stdout=out)
    return out.getvalue()


def test_first_run_reports_what_was_loaded(clock, fake_bnr):
    output = run()

    assert "nbrfxrates2025.xml: 21 cursuri noi (cel mai recent din 31.12.2025)" in output
    assert ExchangeRate.objects.exists()


def test_up_to_date_does_nothing(clock, fake_bnr):
    load("recent.xml")

    assert "la zi" in run()
    assert fake_bnr.calls == []


def test_load_a_specific_year(clock, fake_bnr):
    run("--year", "2025")

    assert fake_bnr.calls == [bnr.year_url(2025)]


def test_failure_is_a_command_error(clock, fake_bnr):
    """Cod de ieșire diferit de 0: un cron sau un monitor vede că job-ul a eșuat."""
    fake_bnr.down = True

    with pytest.raises(CommandError, match="nu răspunde"):
        run()


def test_scheduler_runs_jobs_and_survives_failures(clock, fake_bnr, monkeypatch):
    monkeypatch.setattr(run_scheduler, "JOBS", ["comanda_inexistenta", "fetch_bnr_rates"])
    out, err = StringIO(), StringIO()

    call_command("run_scheduler", "--once", stdout=out, stderr=err)

    assert "comanda_inexistenta a eșuat" in err.getvalue()
    assert ExchangeRate.objects.exists()  # job-ul următor a rulat oricum
