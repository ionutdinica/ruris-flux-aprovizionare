"""Actualizează cursurile BNR.

    python manage.py fetch_bnr_rates               # doar dacă e ceva nou de adus
    python manage.py fetch_bnr_rates --force       # întreabă BNR oricum
    python manage.py fetch_bnr_rates --year 2024   # încarcă arhiva unui an

Rulat periodic de `run_scheduler`. Poate rula oricât de des: descarcă doar când
lipsește un curs (de regulă o dată pe zi, după ora 13:00).
"""

from django.core.management.base import BaseCommand, CommandError

from apps.currency import services


class Command(BaseCommand):
    help = "Descarcă de la BNR cursurile valutare lipsă."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="interoghează BNR oricum")
        parser.add_argument(
            "--year", type=int, action="append", default=[], help="încarcă arhiva unui an"
        )

    def handle(self, *args, force, year, **options):
        syncs = [services.load_year(y) for y in year] or services.sync_rates(force=force)
        if not syncs:
            self.stdout.write("Cursurile sunt la zi; nu e nimic de adus de la BNR.")
            return
        for sync in syncs:
            if sync.success:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{sync.url}: {sync.rates_created} cursuri noi "
                        f"(cel mai recent din {sync.latest_date:%d.%m.%Y})."
                    )
                )
            else:
                raise CommandError(f"{sync.url}: {sync.error}")
