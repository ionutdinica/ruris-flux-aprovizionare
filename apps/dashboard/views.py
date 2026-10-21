from django.utils import timezone
from django.views.generic import TemplateView

from apps.notifications.alerts import Section, collect, for_user, ordered
from apps.notifications.digest import SECTION_COLORS

from .metrics import kpis_for

# Câte probleme se afișează pe panoul Administratorului (care le vede pe ale tuturor).
ADMIN_ALERT_LIMIT = 15


class HomeView(TemplateView):
    """Panoul de start, diferit pe rol: cifrele-cheie și lista „De rezolvat”.

    Lista vine din același detector ca emailul zilnic (apps/notifications/alerts.py):
    panoul și emailul arată aceleași probleme, dar panoul e mereu la zi.
    """

    template_name = "dashboard/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.localdate()
        everything = collect(today)
        is_admin = user.can("alerts.view_all")
        alerts = ordered(everything) if is_admin else for_user(everything, user)

        shown = alerts[:ADMIN_ALERT_LIMIT] if is_admin else alerts
        context.update(
            kpis=kpis_for(user, alerts, today),
            sections=_by_section(shown),
            alert_count=len(alerts),
            hidden_count=len(alerts) - len(shown),
            is_admin=is_admin,
            today=today,
        )
        return context


def _by_section(alerts):
    sections = [
        {
            "title": Section.TITLES[section],
            "color": SECTION_COLORS[section],
            "alerts": [alert for alert in alerts if alert.section == section],
        }
        for section in Section.ORDER
    ]
    return [section for section in sections if section["alerts"]]
