"""Paginile facturilor. Vizualizare: Achiziții, Contabilitate, Admin (invoices.view);
înregistrare, validare și deciziile de plată: Contabilitate și Admin (invoices.edit)."""

from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView
from django.views.generic.edit import CreateView, UpdateView

from apps.accounts.permissions import PermissionMixin
from apps.catalog.models import Supplier
from apps.core.views import SearchListMixin
from apps.currency.services import RateError, get_rate
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine

from . import services
from .forms import (
    InvoiceForm,
    InvoiceLineForm,
    InvoiceLineFormSet,
    PaymentForm,
    ReasonForm,
    invoiceable_order_lines,
    lines_formset_for_order,
)
from .matching import TOTAL_TOLERANCE
from .models import Invoice

Status = Invoice.Status

# Facturile care cer o acțiune din partea Contabilității.
NEEDS_ATTENTION = (Status.REGISTERED, Status.RATE_PENDING, Status.BLOCKED)


# --- Listă -------------------------------------------------------------------------


class InvoiceListView(PermissionMixin, SearchListMixin, ListView):
    permission = "invoices.view"
    model = Invoice
    template_name = "invoicing/invoice_list.html"
    partial_template_name = "invoicing/partials/invoice_table.html"
    status_choices = [
        ("", "Toate"),
        ("attention", "De rezolvat (înregistrate, în așteptare, blocate)"),
        ("overdue", "Scadență depășită, neplătite"),
        *Status.choices,
    ]

    def base_queryset(self):
        queryset = (
            super().base_queryset().select_related("supplier").order_by("-invoice_date", "-number")
        )
        supplier = self.request.GET.get("supplier")
        if supplier and supplier.isdigit():
            queryset = queryset.filter(supplier_id=supplier)
        return queryset

    def filter_status(self, queryset, status):
        if status == "attention":
            return queryset.filter(status__in=NEEDS_ATTENTION)
        if status == "overdue":
            return queryset.filter(_overdue_condition())
        if status in Status.values:
            return queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["suppliers"] = Supplier.objects.filter(invoices__isnull=False).distinct()
        context["supplier_filter"] = self.request.GET.get("supplier", "")
        context["today"] = timezone.localdate()
        return context


def _overdue_condition():
    """Scadența a trecut și factura nu e plătită (nici respinsă)."""
    return Q(due_date__lt=timezone.localdate()) & ~Q(status__in=[Status.PAID, Status.REJECTED])


# --- Ecranul de potrivire ----------------------------------------------------------------


class InvoiceDetailView(PermissionMixin, DetailView):
    permission = "invoices.view"
    model = Invoice
    template_name = "invoicing/invoice_detail.html"
    context_object_name = "invoice"

    def get_queryset(self):
        return super().get_queryset().select_related("supplier", "approved_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoice = self.object
        lines = list(
            invoice.lines.select_related("order_line__order", "order_line__product").order_by("id")
        )
        progress = {
            line.pk: line
            for line in PurchaseOrderLine.objects.with_progress().filter(
                pk__in=[line.order_line_id for line in lines]
            )
        }
        problems = invoice.problems
        flagged = {problem["order_line"] for problem in problems if problem.get("order_line")}
        for line in lines:
            line.progress = progress[line.order_line_id]
            line.flagged = line.order_line_id in flagged
            line.line_problems = [p for p in problems if p.get("order_line") == line.order_line_id]
            line.price_differs = line.unit_price != line.order_line.unit_price

        context.update(
            lines=lines,
            general_problems=[p for p in problems if not p.get("order_line")],
            totals=_totals_comparison(invoice, lines),
            orders=sorted({line.order_line.order for line in lines}, key=lambda o: o.number),
            rate_pending_reason=_rate_pending_reason(invoice),
            today=timezone.localdate(),
        )
        return context


def _totals_comparison(invoice, lines):
    """Totalurile de pe hârtie lângă cele calculate din linii, cu verdict pe fiecare rând."""
    net = sum(line.net_amount for line in lines)
    vat = sum(line.vat_amount for line in lines)
    rows = [
        ("Total fără TVA", invoice.declared_net, net),
        ("TVA", invoice.declared_vat, vat),
        ("Total de plată", invoice.declared_total, net + vat),
    ]
    return [
        {
            "label": label,
            "declared": declared,
            "computed": computed,
            "ok": abs(declared - computed) <= TOTAL_TOLERANCE,
        }
        for label, declared, computed in rows
    ]


def _rate_pending_reason(invoice):
    if invoice.status != Status.RATE_PENDING:
        return ""
    try:
        get_rate(invoice.currency, invoice.invoice_date)
    except RateError as exc:
        return str(exc)
    return "Cursul e disponibil; factura se finalizează la următoarea actualizare."


# --- Înregistrare / editare (antet + linii) ------------------------------------------------


class InvoiceFormMixin(PermissionMixin):
    permission = "invoices.edit"
    model = Invoice
    form_class = InvoiceForm
    template_name = "invoicing/invoice_form.html"

    def _supplier_id(self):
        """Furnizorul după care se aleg liniile de comandă: din formularul trimis, din
        factura editată sau din adresă (ex. „Înregistrează factura” de pe o comandă)."""
        value = self.request.POST.get("supplier") or self.request.GET.get("furnizor") or ""
        if value.isdigit():
            return int(value)
        if self.object:
            return self.object.supplier_id
        order = self._source_order()
        return order.supplier_id if order else None

    def _source_order(self):
        """Comanda de pe care s-a apăsat „Înregistrează factura” (?comanda=ID), dacă există."""
        value = self.request.GET.get("comanda", "")
        if self.request.method != "GET" or self.object or not value.isdigit():
            return None
        return PurchaseOrder.objects.filter(pk=value).first()

    def get_initial(self):
        initial = super().get_initial()
        supplier_id = self._supplier_id()
        if supplier_id and not self.object:
            supplier = Supplier.objects.filter(pk=supplier_id).first()
            if supplier:
                initial.update(supplier=supplier, currency=supplier.default_currency)
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "lines" not in context:
            order = self._source_order()
            if order:
                context["lines"] = lines_formset_for_order(order)
            else:
                context["lines"] = InvoiceLineFormSet(
                    instance=self.object or Invoice(), supplier_id=self._supplier_id()
                )
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object() if "pk" in kwargs else None
        form = self.get_form()
        invoice = form.instance if form.is_valid() else (self.object or Invoice())
        lines = InvoiceLineFormSet(request.POST, instance=invoice, supplier_id=self._supplier_id())
        if form.is_valid() and lines.is_valid():
            return self.forms_valid(form, lines)
        return self.render_to_response(self.get_context_data(form=form, lines=lines))

    def forms_valid(self, form, lines):
        with transaction.atomic():  # antetul și liniile: ori toate, ori nimic
            self.object = form.save()
            lines.instance = self.object
            lines.save()
        if "validate" in self.request.POST:
            return _validate_and_report(self.request, self.object)
        messages.success(
            self.request,
            f"Factura {self.object} a fost salvată. Când datele sunt complete, apasă „Validează”.",
        )
        return HttpResponseRedirect(self.object.get_absolute_url())


class InvoiceCreateView(InvoiceFormMixin, CreateView):
    extra_context = {"page_title": "Factură nouă"}


class InvoiceUpdateView(InvoiceFormMixin, UpdateView):
    extra_context = {"page_title": "Editare factură"}

    # Statusul se verifică după permisiune (vezi OrderUpdateView, același motiv).
    def get(self, request, *args, **kwargs):
        return self._refuse_if_locked() or super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        return self._refuse_if_locked() or super().post(request, *args, **kwargs)

    def _refuse_if_locked(self):
        invoice = get_object_or_404(Invoice, pk=self.kwargs["pk"])
        if invoice.is_editable:
            return None
        status = invoice.get_status_display().lower()
        hint = " Redeschide-o pentru corectare." if invoice.status == Status.BLOCKED else ""
        messages.error(
            self.request, f"Factura {invoice} nu mai poate fi modificată ({status}).{hint}"
        )
        return redirect(invoice)


class OrderLineOptionsView(PermissionMixin, View):
    """Câmpul „linie de comandă” pentru furnizorul ales (la schimbarea furnizorului).

    Se trimite câmpul complet, randat exact ca în formular; static/js/invoice_form.js
    îi preia opțiunile. Un singur loc decide cum arată o opțiune: OrderLineSelect.
    """

    permission = "invoices.edit"

    def get(self, request):
        supplier = request.GET.get("furnizor", "")
        if supplier.isdigit():
            lines = invoiceable_order_lines(int(supplier))
        else:
            lines = PurchaseOrderLine.objects.none()
        form = InvoiceLineForm(order_lines=lines)
        return render(request, "invoicing/partials/order_line_options.html", {"form": form})


# --- Validare și corectare -------------------------------------------------------------------


def _validate_and_report(request, invoice):
    try:
        invoice = services.validate_invoice(invoice)
    except services.InvoiceError as error:
        messages.error(request, " ".join(error.messages))
        return redirect(invoice)
    if invoice.status == Status.MATCHED:
        messages.success(
            request, f"Factura {invoice} corespunde comenzii și recepției. Poate fi aprobată."
        )
    elif invoice.status == Status.BLOCKED:
        count = len(invoice.problems)
        messages.warning(
            request,
            f"Factura {invoice} este blocată: {count} "
            f"{'motiv' if count == 1 else 'motive'} de lămurit, detaliate mai jos.",
        )
    else:
        messages.info(
            request,
            f"Factura {invoice} așteaptă cursul BNR; se finalizează automat când e publicat.",
        )
    return redirect(invoice)


class InvoiceValidateView(PermissionMixin, View):
    permission = "invoices.edit"
    http_method_names = ["post"]

    def post(self, request, pk):
        return _validate_and_report(request, get_object_or_404(Invoice, pk=pk))


class InvoiceReopenView(PermissionMixin, View):
    permission = "invoices.edit"
    http_method_names = ["post"]

    def post(self, request, pk):
        invoice = get_object_or_404(Invoice, pk=pk)
        try:
            services.reopen_invoice(invoice)
        except services.InvoiceError as error:
            messages.error(request, " ".join(error.messages))
            return redirect(invoice)
        messages.info(
            request, f"Factura {invoice} a fost redeschisă. Corectează datele și validează din nou."
        )
        return redirect("invoicing:invoice_update", pk=invoice.pk)


# --- Deciziile Contabilității: aprobare, forțare, plată, respingere -------------------------


class InvoiceActionView(PermissionMixin, View):
    """O acțiune de status pe factură: doar prin POST, cu mesaj de confirmare sau eroare."""

    permission = "invoices.edit"
    http_method_names = ["post"]
    form_class = None  # formularul cu date suplimentare (motiv, data plății)
    success_message = ""

    def post(self, request, pk):
        invoice = get_object_or_404(Invoice, pk=pk)
        data = {}
        if self.form_class:
            form = self.form_class(request.POST)
            if not form.is_valid():
                errors = [e for field_errors in form.errors.values() for e in field_errors]
                messages.error(request, " ".join(errors))
                return redirect(invoice)
            data = form.cleaned_data
        try:
            self.act(invoice, data)
        except services.InvoiceError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, self.success_message % {"number": invoice.number})
        return redirect(invoice)


class InvoiceApproveView(InvoiceActionView):
    success_message = "Factura %(number)s a fost aprobată la plată."

    def act(self, invoice, data):
        services.approve_invoice(invoice, self.request.user)


class InvoiceForceApproveView(InvoiceActionView):
    form_class = ReasonForm
    success_message = "Factura %(number)s a fost forțată la plată; justificarea e în jurnal."

    def act(self, invoice, data):
        services.force_approve_invoice(invoice, self.request.user, data["reason"])


class InvoicePayView(InvoiceActionView):
    form_class = PaymentForm
    success_message = "Factura %(number)s a fost marcată plătită."

    def act(self, invoice, data):
        services.mark_paid(invoice, data["paid_at"], data["reference"])


class InvoiceRejectView(InvoiceActionView):
    form_class = ReasonForm
    success_message = "Factura %(number)s a fost respinsă."

    def act(self, invoice, data):
        services.reject_invoice(invoice, data["reason"])
