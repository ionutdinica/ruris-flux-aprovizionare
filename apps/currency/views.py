import datetime
from urllib.parse import urlencode

from django.contrib import messages
from django.db.models import F, Window
from django.db.models.functions import Lag
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import ListView

from apps.accounts.permissions import PermissionMixin
from apps.core.models import Currency

from . import services
from .models import ExchangeRate

DEFAULT_CURRENCY = Currency.EUR


def _selected_currency(request):
    currency = request.GET.get("moneda", "").upper()
    return currency if ExchangeRate.objects.filter(currency=currency).exists() else DEFAULT_CURRENCY


def _lookup(request, currency):
    """Răspunsul la „ce curs se aplică unei facturi din data X?” (I-25…I-28)."""
    try:
        day = datetime.date.fromisoformat(request.GET.get("data", ""))
    except ValueError:
        return {"lookup_day": None}
    context = {"lookup_day": day}
    try:
        context["quote"] = services.get_rate(currency, day)
    except services.RatePending as exc:
        context["lookup_pending"] = str(exc)
    except services.InvalidRateDate as exc:
        context["lookup_error"] = str(exc)
    return context


class RateListView(PermissionMixin, ListView):
    """Istoricul cursurilor unei monede, cu variația zilnică și starea actualizării."""

    permission = "rates.view"
    template_name = "currency/rate_list.html"
    paginate_by = 30

    def get_queryset(self):
        self.currency = _selected_currency(self.request)
        return (
            ExchangeRate.objects.filter(currency=self.currency)
            # Cursul zilei de publicare anterioare, pentru variație. Funcția fereastră
            # se calculează în baza de date, înainte de împărțirea pe pagini.
            .annotate(previous=Window(Lag("rate"), order_by=F("date").asc()))
            .order_by("-date")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for rate in context["object_list"]:
            rate.change = None if rate.previous is None else rate.rate - rate.previous
        today = services.local_now().date()
        try:
            context["today_quote"] = services.get_rate(self.currency, today)
        except services.RatePending as exc:
            context["today_pending"] = str(exc)
        context.update(
            currency=self.currency,
            currencies=ExchangeRate.objects.values_list("currency", flat=True)
            .order_by("currency")
            .distinct(),
            today=today,
            last_sync=services.last_sync(),
            last_successful_sync=services.last_successful_sync(),
            **_lookup(self.request, self.currency),
        )
        return context


class RateLookupView(PermissionMixin, View):
    """Fragmentul HTMX pentru „ce curs se aplică?”; fără JavaScript răspunde lista."""

    permission = "rates.view"

    def get(self, request):
        currency = _selected_currency(request)
        context = {"currency": currency, **_lookup(request, currency)}
        return render(request, "currency/_rate_lookup.html", context)


class RateRefreshView(PermissionMixin, View):
    """„Actualizează acum”: întreabă BNR imediat, fără să aștepte job-ul."""

    permission = "rates.refresh"

    def post(self, request):
        syncs = services.sync_rates(user=request.user, force=True)
        last = syncs[-1]
        if not last.success:
            messages.error(request, f"Actualizarea a eșuat: {last.error} Se reîncearcă automat.")
        else:
            created = sum(s.rates_created for s in syncs)
            latest = services.latest_rate_date()
            if created:
                messages.success(
                    request,
                    f"Cursurile au fost actualizate: {created} cursuri noi, cel mai recent "
                    f"din {latest:%d.%m.%Y}.",
                )
            else:
                messages.info(
                    request,
                    f"BNR nu are cursuri noi; cel mai recent rămâne cel din {latest:%d.%m.%Y}.",
                )
        url = reverse("currency:rate_list")
        currency = request.POST.get("moneda")
        return redirect(f"{url}?{urlencode({'moneda': currency})}" if currency else url)
