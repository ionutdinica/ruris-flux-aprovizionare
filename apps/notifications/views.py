"""Pagina „Notificări trimise”: fiecare își vede emailurile primite, Adminul pe toate
(docs/04-permisiuni.md), plus butonul „Trimite acum” (doar Admin)."""

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.views import View
from django.views.generic import DetailView, ListView

from apps.accounts.permissions import PermissionMixin

from . import services
from .models import DailyDigestRun, NotificationLog


class VisibleNotificationsMixin:
    """Cine nu le vede pe toate le vede doar pe ale lui; ale altora dau 404, nu 403
    (nu dezvăluim nici măcar că există)."""

    def get_queryset(self):
        queryset = NotificationLog.objects.select_related("recipient", "triggered_by")
        if self.request.user.can("notifications.view_all"):
            return queryset
        return queryset.filter(recipient=self.request.user)


class NotificationListView(PermissionMixin, VisibleNotificationsMixin, ListView):
    permission = "notifications.view_own"
    template_name = "notifications/notification_list.html"
    paginate_by = 25

    def get_queryset(self):
        queryset = super().get_queryset()
        status = self.request.GET.get("status", "")
        if status in NotificationLog.Status.values:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["status"] = self.request.GET.get("status", "")
        context["statuses"] = NotificationLog.Status.choices
        context["sees_all"] = user.can("notifications.view_all")
        context["notification_hour"] = settings.NOTIFICATION_HOUR
        if context["sees_all"]:
            context["runs"] = DailyDigestRun.objects.all()[:7]
        if user.can("notifications.send_now"):
            context["recipients"] = services.digest_recipients()
        return context


class NotificationDetailView(PermissionMixin, VisibleNotificationsMixin, DetailView):
    permission = "notifications.view_own"
    template_name = "notifications/notification_detail.html"
    context_object_name = "notification"


class SendNowView(PermissionMixin, View):
    """„Trimite acum”: tuturor sau unei singure persoane."""

    permission = "notifications.send_now"
    http_method_names = ["post"]

    def post(self, request):
        recipients = services.digest_recipients()
        chosen = request.POST.get("recipient", "")
        if chosen.isdigit():
            recipients = recipients.filter(pk=chosen)
        logs, nothing = services.send_now(triggered_by=request.user, recipients=recipients)

        sent = sum(1 for log in logs if log.status == NotificationLog.Status.SENT)
        failed = len(logs) - sent
        summary = f"Rezumate trimise: {sent}"
        if failed:
            summary += f", eșuate: {failed} (vezi eroarea în listă)"
        if nothing:
            summary += (
                f"; {nothing} {'persoană' if nothing == 1 else 'persoane'} fără nimic de rezolvat"
            )
        level = messages.warning if failed else messages.success
        level(request, summary + ".")
        return redirect("notifications:log")
