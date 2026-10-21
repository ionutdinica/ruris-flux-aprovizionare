"""Generatorul datelor demo: o firmă care lucrează de ~4 luni.

Totul se creează prin aceleași reguli ca aplicația (services.py, full_clean), nu prin
inserări directe: demo-ul nu poate conține o stare imposibilă (o factură e „potrivită”
pentru că motorul de potrivire a decis asta). Fiecare acțiune se petrece la data ei,
în trecut (clock.travel_to), și în numele omului care ar face-o (acting_as), deci
jurnalul de audit spune o poveste coerentă.

Datele sunt relative la ziua rulării: comenzile „întârziate” sunt întârziate față de azi.
Aleatoriul are sămânță fixă: aceeași zi de rulare dă exact aceleași date.
"""

import datetime
import random
from contextlib import contextmanager

from auditlog.context import set_actor
from django.utils import timezone

from apps.audit.context import audit_context

from .catalog import create_catalog, create_team
from .clock import travel_to

HISTORY_DAYS = 120  # cât de departe în trecut începe activitatea
RANDOM_SEED = 2026


@contextmanager
def acting_as(user):
    """Acțiunile din bloc apar în jurnal ca făcute de `user` (ambele jurnale de audit)."""
    with audit_context(actor=user), set_actor(user):
        yield


def moment(day, hour=9, minute=0):
    """Dată-oră locală (București) pentru o zi și o oră."""
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(hour, minute)))


class DemoSeeder:
    def __init__(self, password, today=None):
        self.password = password
        self.today = today or timezone.localdate()
        self.start = self.today - datetime.timedelta(days=HISTORY_DAYS)
        self.random = random.Random(RANDOM_SEED)
        self.log = []  # ce s-a creat, pentru rezumatul afișat la final

    def run(self):
        self.create_base_data()
        return self.log

    def create_base_data(self):
        """Echipa și catalogul există dinaintea primei comenzi."""
        with travel_to(moment(self.start - datetime.timedelta(days=7))):
            self.users = create_team(self.password)
            with acting_as(self.users["andrei.ionescu"]):
                self.suppliers, self.products = create_catalog()
        self.log.append(
            f"{len(self.users)} utilizatori, {len(self.suppliers)} furnizori, "
            f"{len(self.products)} produse"
        )
