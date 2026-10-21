"""Datele demo pentru teste: fără internet (cursurile EUR sunt puse direct, valori de test)."""

import datetime
from decimal import Decimal

from django.utils import timezone

from apps.currency.bnr import PublishedRate
from apps.currency.services import store_rates

from .seed import HISTORY_DAYS, DemoSeeder

PASSWORD = "parola-demo-123"


def seed_demo_for_tests():
    """Generează datele demo complete. Întoarce generatorul (scenariile) și rezumatul."""
    today = timezone.localdate()
    day = today - datetime.timedelta(days=HISTORY_DAYS + 30)
    rates = []
    while day < today:
        if day.weekday() < 5:
            rates.append(PublishedRate(day, "EUR", Decimal("5.0") + Decimal(day.day) / 1000, 1))
        day += datetime.timedelta(days=1)
    store_rates(rates)
    seeder = DemoSeeder(PASSWORD, fetch_rates=False)
    return seeder, seeder.run()
