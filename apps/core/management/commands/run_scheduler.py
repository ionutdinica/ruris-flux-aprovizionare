"""Planificatorul: rulează periodic job-urile aplicației, într-un proces separat.

    python manage.py run_scheduler              # la nesfârșit, la fiecare 10 minute
    python manage.py run_scheduler --once       # o singură trecere (ex. dintr-un cron)

Fiecare job e o comandă `manage.py` care știe singură dacă are ceva de făcut
(ex. fetch_bnr_rates descarcă doar când lipsește un curs). De aceea planificatorul
poate fi simplu: nu ține minte nimic, doar le pornește pe toate, la intervale fixe.
Dacă procesul repornește, nu se pierde și nu se dublează nimic.
"""

import logging
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS, close_old_connections, connections
from django.db.migrations.executor import MigrationExecutor

logger = logging.getLogger(__name__)

JOBS = [
    "fetch_bnr_rates",  # cursurile BNR (capitolul 6)
]


class Command(BaseCommand):
    help = "Rulează periodic job-urile aplicației (cursuri BNR, notificări)."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=600, help="secunde între treceri")
        parser.add_argument("--once", action="store_true", help="o singură trecere")

    def handle(self, *args, interval, once, **options):
        self._wait_for_migrations(interval)
        while True:
            self.run_jobs()
            if once:
                return
            time.sleep(interval)
            # După o pauză lungă, serverul bazei de date poate închide conexiunea;
            # o renunțăm pe cea veche, iar Django deschide automat una nouă.
            close_old_connections()

    def run_jobs(self):
        for job in JOBS:
            try:
                call_command(job, stdout=self.stdout, stderr=self.stderr)
            except Exception:
                # Un job care eșuează nu oprește planificatorul și nici celelalte job-uri.
                logger.exception("Job-ul %s a eșuat", job)
                self.stderr.write(f"Job-ul {job} a eșuat; se reia la trecerea următoare.")

    def _wait_for_migrations(self, interval):
        """În Docker, planificatorul poate porni înaintea aplicației care aplică migrațiile."""
        while True:
            executor = MigrationExecutor(connections[DEFAULT_DB_ALIAS])
            if not executor.migration_plan(executor.loader.graph.leaf_nodes()):
                return
            self.stdout.write("Aștept aplicarea migrațiilor bazei de date...")
            time.sleep(min(interval, 10))
