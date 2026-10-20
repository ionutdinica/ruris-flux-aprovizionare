"""Paginile comenzilor. Vizualizare: toate rolurile (orders.view), fără ciorne
pentru cei din afara Achizițiilor; modificare și statusuri: Achiziții și Admin
(orders.edit). Prețurile sunt ascunse pentru Depozit (orders.view_prices)."""

import secrets

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, FormView, ListView
from django.views.generic.edit import CreateView, UpdateView

from apps.accounts.permissions import PermissionMixin
from apps.audit.models import BusinessEvent
from apps.audit.services import record_event
from apps.catalog.models import Supplier
from apps.core.excel import xlsx_response
from apps.core.views import SearchListMixin
from apps.warehouse.models import GoodsReceipt

from . import excel_import, services
from .excel_export import build_import_template, build_orders_export
from .forms import ImportFileForm, PurchaseOrderForm, PurchaseOrderLineFormSet, ReasonForm
from .models import PurchaseOrder, PurchaseOrderLine

Status = PurchaseOrder.Status


class VisibleOrdersMixin:
    def get_queryset(self):
        return super().get_queryset().visible_to(self.request.user)


# --- Listă -------------------------------------------------------------------------


class OrderListView(PermissionMixin, VisibleOrdersMixin, SearchListMixin, ListView):
    permission = "orders.view"
    model = PurchaseOrder
    template_name = "purchasing/order_list.html"
    partial_template_name = "purchasing/partials/order_table.html"
    status_choices = [
        ("", "Toate"),
        ("open", "Deschise (se așteaptă marfă)"),
        ("late", "Întârziate"),
        *Status.choices,
    ]

    def base_queryset(self):
        queryset = (
            super()
            .base_queryset()
            .select_related("supplier", "owner")
            .with_totals()
            .with_late_flag()
            # Explicit: cu Sum() (totaluri), Django ignoră ordonarea implicită a modelului,
            # iar paginarea fără ordonare stabilă poate repeta sau sări comenzi.
            .order_by("-order_date", "-number")
        )
        supplier = self.request.GET.get("supplier")
        if supplier and supplier.isdigit():
            queryset = queryset.filter(supplier_id=supplier)
        return queryset

    def filter_status(self, queryset, status):
        if status == "open":
            return queryset.open()
        if status == "late":
            return queryset.filter(is_late=True)  # calculat în base_queryset()
        if status in Status.values:
            return queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["suppliers"] = Supplier.objects.filter(orders__isnull=False).distinct()
        context["supplier_filter"] = self.request.GET.get("supplier", "")
        return context

    def describe_filters(self):
        """Filtrele curente, pe înțelesul omului (pentru export și jurnal)."""
        parts = []
        query = self.request.GET.get("q", "").strip()
        if query:
            parts.append(f"căutare „{query}”")
        status = self.request.GET.get("status", "")
        if status:
            parts.append(f"status: {dict(self.status_choices).get(status, status)}")
        supplier_id = self.request.GET.get("supplier", "")
        if supplier_id.isdigit():
            supplier = Supplier.objects.filter(pk=supplier_id).first()
            if supplier:
                parts.append(f"furnizor: {supplier}")
        return "; ".join(parts)


class OrderExportView(OrderListView):
    """Lista de comenzi, cu filtrele curente, ca fișier Excel (fără paginare)."""

    permission = "orders.export"
    paginate_by = None

    def get(self, request, *args, **kwargs):
        orders = list(self.get_queryset().prefetch_related("lines"))
        lines = (
            PurchaseOrderLine.objects.with_progress()
            .filter(order__in=[order.pk for order in orders])
            .select_related("order__supplier", "product")
            .order_by("-order__order_date", "-order__number", "id")
        )
        filters = self.describe_filters()
        workbook = build_orders_export(orders, lines, user=request.user, filters=filters)
        record_event(
            BusinessEvent.Type.ORDERS_EXPORTED,
            f"Export Excel: {len(orders)} comenzi.",
            data={"filtre": filters or "fără filtre"},
        )
        return xlsx_response(workbook, f"comenzi_{timezone.localdate():%Y-%m-%d}.xlsx")


# --- Detaliu ----------------------------------------------------------------------


class OrderDetailView(PermissionMixin, VisibleOrdersMixin, DetailView):
    permission = "orders.view"
    model = PurchaseOrder
    template_name = "purchasing/order_detail.html"
    context_object_name = "order"

    def get_queryset(self):
        return super().get_queryset().select_related("supplier", "owner")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order = self.object
        context["lines"] = (
            PurchaseOrderLine.objects.with_progress().filter(order=order).select_related("product")
        )
        context["reason_form"] = ReasonForm()
        context["can_cancel"] = order.status in (Status.DRAFT, Status.SENT)
        context["receipts"] = order.receipts.select_related("confirmed_by")
        context["can_receive"] = order.status in GoodsReceipt.RECEIVABLE_ORDER_STATUSES
        return context


# --- Adăugare / editare (antet + linii) -------------------------------------------------


class OrderFormMixin(PermissionMixin):
    permission = "orders.edit"
    model = PurchaseOrder
    form_class = PurchaseOrderForm
    template_name = "purchasing/order_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "lines" not in context:
            context["lines"] = PurchaseOrderLineFormSet(instance=self.object or PurchaseOrder())
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object() if "pk" in kwargs else None
        form = self.get_form()
        # Formularul liniilor primește comanda (încă nesalvată, la „Comandă nouă”),
        # ca validările liniilor să cunoască data și statusul comenzii.
        order = form.instance if form.is_valid() else (self.object or PurchaseOrder())
        lines = PurchaseOrderLineFormSet(request.POST, instance=order)
        if form.is_valid() and lines.is_valid():
            return self.forms_valid(form, lines)
        return self.render_to_response(self.get_context_data(form=form, lines=lines))

    @transaction.atomic
    def forms_valid(self, form, lines):
        """Antetul și liniile se salvează împreună: ori toate, ori nimic."""
        self.object = form.save()
        lines.instance = self.object
        lines.save()
        services.refresh_status(self.object)  # ex. o linie nouă pe o comandă recepționată
        messages.success(self.request, self.success_message % {"number": self.object.number})
        return HttpResponseRedirect(self.object.get_absolute_url())


class OrderCreateView(OrderFormMixin, CreateView):
    success_message = "Comanda %(number)s a fost salvată ca ciornă."
    extra_context = {"page_title": "Comandă nouă"}

    def get_initial(self):
        return {"owner": self.request.user}


class OrderUpdateView(OrderFormMixin, UpdateView):
    success_message = "Modificările la comanda %(number)s au fost salvate."
    extra_context = {"page_title": "Editare comandă"}

    # Verificarea statusului se face în get()/post(), adică DUPĂ verificarea
    # permisiunii (PermissionMixin.dispatch). Invers, cine nu are acces ar afla
    # din mesaj ce comenzi există și în ce status sunt (bug prins de teste).
    def get(self, request, *args, **kwargs):
        return self._refuse_if_locked() or super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        return self._refuse_if_locked() or super().post(request, *args, **kwargs)

    def _refuse_if_locked(self):
        order = get_object_or_404(PurchaseOrder, pk=self.kwargs["pk"])
        if order.is_editable or order.is_amendable:
            return None
        status = order.get_status_display().lower()
        messages.error(self.request, f"Comanda {order} nu mai poate fi modificată ({status}).")
        return redirect(order)


# --- Tranziții de status ------------------------------------------------------------------


class OrderTransitionView(PermissionMixin, View):
    """Acțiunile de status: doar prin POST (un link simplu nu poate trimite o comandă)."""

    permission = "orders.edit"
    http_method_names = ["post"]
    needs_reason = False
    success_message = ""

    def post(self, request, pk):
        order = get_object_or_404(PurchaseOrder, pk=pk)
        args = []
        if self.needs_reason:
            form = ReasonForm(request.POST)
            if not form.is_valid():
                messages.error(request, "Motivul este obligatoriu.")
                return redirect(order)
            args.append(form.cleaned_data["reason"])
        try:
            self.transition(order, *args)
        except services.TransitionError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, self.success_message % {"number": order.number})
        return redirect(order)


class OrderSendView(OrderTransitionView):
    transition = staticmethod(services.send_order)
    success_message = (
        "Comanda %(number)s a fost trimisă. De acum Depozitul o vede la livrări așteptate."
    )


class OrderCancelView(OrderTransitionView):
    transition = staticmethod(services.cancel_order)
    needs_reason = True
    success_message = "Comanda %(number)s a fost anulată."


class OrderCloseView(OrderTransitionView):
    transition = staticmethod(services.close_order)
    needs_reason = True
    success_message = "Comanda %(number)s a fost închisă cu rest nelivrat."


# --- Import din Excel ------------------------------------------------------------------------

IMPORT_SESSION_KEY = "order_import"


class OrderImportTemplateView(PermissionMixin, View):
    permission = "orders.import"

    def get(self, request):
        return xlsx_response(build_import_template(), "sablon_import_comenzi.xlsx")


class OrderImportView(PermissionMixin, FormView):
    """Pasul 1: încărcarea fișierului → validare completă → previzualizare sau erori."""

    permission = "orders.import"
    template_name = "purchasing/order_import.html"
    form_class = ImportFileForm

    def form_valid(self, form):
        uploaded = form.cleaned_data["file"]
        try:
            rows = excel_import.read_rows(uploaded)
        except excel_import.ImportFileError as error:
            form.add_error("file", str(error))
            return self.form_invalid(form)

        plan = excel_import.plan_import(rows, self.request.user)
        context = {"plan": plan, "filename": uploaded.name}
        if plan.is_valid:
            # Rândurile citite așteaptă confirmarea în sesiune. Token-ul leagă confirmarea
            # de ACEASTĂ previzualizare (nu de una mai veche, deschisă în alt tab).
            context["token"] = token = secrets.token_urlsafe(16)
            self.request.session[IMPORT_SESSION_KEY] = {
                "token": token,
                "filename": uploaded.name,
                "rows": rows,
            }
        return self.render_to_response(self.get_context_data(**context))


class OrderImportConfirmView(PermissionMixin, View):
    """Pasul 2: confirmarea previzualizării → comenzile se creează ca ciorne."""

    permission = "orders.import"
    http_method_names = ["post"]

    def post(self, request):
        pending = request.session.get(IMPORT_SESSION_KEY)
        if not pending or pending["token"] != request.POST.get("token"):
            messages.warning(
                request, "Importul a expirat sau a fost deja efectuat. Încarcă din nou fișierul."
            )
            return redirect("purchasing:order_import")
        del request.session[IMPORT_SESSION_KEY]  # o previzualizare se confirmă o singură dată

        # Validare din nou: de la previzualizare, un produs putea fi dezactivat etc.
        plan = excel_import.plan_import(pending["rows"], request.user)
        if not plan.is_valid:
            messages.error(
                request,
                "Datele s-au schimbat de la previzualizare, iar importul nu a fost efectuat. "
                "Corectează erorile de mai jos și încarcă din nou fișierul.",
            )
            context = {"form": ImportFileForm(), "plan": plan, "filename": pending["filename"]}
            return render(request, "purchasing/order_import.html", context)

        try:
            created = excel_import.execute_import(plan, pending["filename"])
        except IntegrityError:  # aceleași comenzi importate simultan, din alt tab
            messages.error(request, "Comenzile din acest fișier au fost deja importate.")
            return redirect("purchasing:order_import")

        messages.success(
            request,
            f"Au fost importate {len(created)} comenzi ca ciorne ({created[0]} – {created[-1]}). "
            "Verifică-le și trimite-le furnizorilor.",
        )
        return redirect(f"{reverse('purchasing:order_list')}?status={Status.DRAFT}")
