"""Reacțiile automate ale facturilor la evenimente din alte module (prin semnale)."""

from django.dispatch import receiver

from apps.currency.signals import rates_synced
from apps.purchasing.signals import order_progress_changed

from . import services


@receiver(order_progress_changed)
def recheck_after_order_change(sender, order, **kwargs):
    """Recepție nouă, retur, comandă modificată: facturile blocate se pot debloca
    singure (sau cele potrivite se pot bloca, ex. după un retur)."""
    services.recheck_order(order)


@receiver(rates_synced)
def resume_after_rates(sender, **kwargs):
    """Cursuri BNR noi: facturile în „Curs în așteptare” se finalizează."""
    services.resume_rate_pending()
