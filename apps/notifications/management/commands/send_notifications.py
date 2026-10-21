"""Rezumatul zilnic pe email.

    python manage.py send_notifications           # doar dacă e momentul (zi lucrătoare, ora)
    python manage.py send_notifications --now     # acum, tuturor (ex. la o demonstrație)

Rulat periodic de `run_scheduler`. Poate rula oricât de des: rezumatul zilei se face
o singură dată (vezi services.send_daily_digests).
"""

from django.core.management.base import BaseCommand

from apps.notifications import services
from apps.notifications.models import NotificationLog


class Command(BaseCommand):
    help = "Trimite rezumatul zilnic cu problemele fiecărei persoane."

    def add_arguments(self, parser):
        parser.add_argument(
            "--now", action="store_true", help="trimite acum, tuturor, indiferent de oră"
        )

    def handle(self, *args, now, **options):
        if now:
            logs, _ = services.send_now()
        else:
            logs = services.send_daily_digests()
        if not logs:
            self.stdout.write("Nimic de trimis acum.")
        for log in logs:
            line = f"{log.email}: {log.subject}"
            if log.status == NotificationLog.Status.SENT:
                self.stdout.write(self.style.SUCCESS(f"Trimis → {line}"))
            else:
                self.stderr.write(self.style.ERROR(f"Eșuat → {line} ({log.error})"))
