"""Generează datele demo: ~4 luni de activitate, cu fiecare situație din cerință.

    python manage.py seed_demo                      # doar pe o bază de date goală
    python manage.py seed_demo --password Parola1   # parola conturilor demo
    python manage.py seed_demo --reset              # ȘTERGE tot și regenerează
                                                    # (doar cu DEMO_RESET_ALLOWED=True)

Fără --password, se generează o parolă aleatorie, afișată o singură dată. Parola nu
apare în cod și nici în Git.
"""

import secrets

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.catalog.models import Product, Supplier
from apps.demo.catalog import TEAM
from apps.demo.seed import DemoSeeder
from apps.purchasing.models import PurchaseOrder


class Command(BaseCommand):
    help = "Generează date demo realiste (doar pe o bază de date goală sau cu --reset)."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="parola conturilor demo (implicit: aleatorie)")
        parser.add_argument(
            "--reset", action="store_true", help="șterge TOATE datele înainte (cu permisiune)"
        )

    def handle(self, *args, password, reset, **options):
        if reset:
            if not settings.DEMO_RESET_ALLOWED:
                raise CommandError(
                    "--reset șterge toată baza de date și e permis doar unde "
                    "DEMO_RESET_ALLOWED=True (calculatorul dezvoltatorului, serverul demo)."
                )
            self.stdout.write("Șterg datele existente...")
            call_command("flush", interactive=False, verbosity=0)
        elif _has_data():
            raise CommandError(
                "Baza de date conține deja date; nu le amestec cu date demo. "
                "Pe o bază de test: seed_demo --reset (cu DEMO_RESET_ALLOWED=True)."
            )

        generated = password is None
        password = password or secrets.token_urlsafe(9)
        with transaction.atomic():  # ori tot demo-ul, ori nimic
            created = DemoSeeder(password).run()

        self.stdout.write(self.style.SUCCESS("Date demo generate:"))
        for line in created:
            self.stdout.write(f"  - {line}")
        self.stdout.write("\nConturi (aceeași parolă pentru toate):")
        for username, first, last, role in TEAM:
            self.stdout.write(f"  {username:<16} {first} {last} · {User.Role(role).label}")
        if generated:
            self.stdout.write(self.style.WARNING(f"\nParola generată: {password}  (notează-o)"))


def _has_data():
    return any(model.objects.exists() for model in (User, Supplier, Product, PurchaseOrder))
