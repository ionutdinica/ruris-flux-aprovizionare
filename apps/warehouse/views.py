"""Paginile depozitului. Vizualizare: toate rolurile (receipts.view); recepția,
confirmarea și ștergerea ciornelor: Depozit și Admin (receipts.edit).
Nicio pagină de aici nu afișează prețuri."""

from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from apps.accounts.permissions import PermissionMixin
from apps.core.views import SearchListMixin
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine

from . import services
from .forms import ReceiptForm, receipt_line_formset
from .models import Discrepancy, GoodsReceipt
from .selectors import expected_deliveries

ZERO = Decimal("0")


# --- Livrări așteptate ----------------------------------------------------------------------


class ExpectedDeliveriesView(PermissionMixin, SearchListMixin, ListView):
    """Pagina de start a Depozitului: ce marfă trebuie să sosească și când."""

    permission = "receipts.view"
    template_name = "warehouse/expected_deliveries.html"
    partial_template_name = "warehouse/partials/expected_table.html"
    status_choices = [
        ("", "Toate"),
        ("late", "Întârziate"),
        ("today", "Așteptate azi"),
        ("week", "În următoarele 7 zile"),
    ]

    def base_queryset(self):
        return expected_deliveries()

    def filter_status(self, queryset, status):
        today = timezone.localdate()
        if status == "late":
            return queryset.filter(next_expected__lt=today)
        if status == "today":
            return queryset.filter(next_expected=today)
        if status == "week":
            return queryset.filter(next_expected__lte=today + timedelta(days=7))
        return queryset

    def get_context_data(self, **kwargs):
        return super().get_context_data(today=timezone.localdate(), **kwargs)


# --- Lista recepțiilor --------------------------------------------------------------------------


class ReceiptListView(PermissionMixin, SearchListMixin, ListView):
    permission = "receipts.view"
    model = GoodsReceipt
    template_name = "warehouse/receipt_list.html"
    partial_template_name = "warehouse/partials/receipt_table.html"
    status_choices = [
        ("", "Toate"),
        (GoodsReceipt.Status.DRAFT, "Ciorne (neconfirmate)"),
        (GoodsReceipt.Status.CONFIRMED, "Confirmate"),
        ("quarantine", "Cu marfă în carantină"),
    ]

    def base_queryset(self):
        open_discrepancies = Discrepancy.objects.filter(
            receipt_line__receipt=OuterRef("pk"), status=Discrepancy.Status.OPEN
        )
        return (
            super()
            .base_queryset()
            .select_related("supplier", "purchase_order", "confirmed_by")
            .annotate(has_quarantine=Exists(open_discrepancies))
        )

    def filter_status(self, queryset, status):
        if status == "quarantine":
            return queryset.filter(has_quarantine=True)
        if status in GoodsReceipt.Status.values:
            return queryset.filter(status=status)
        return queryset


# --- Detaliu, confirmare, ștergere ---------------------------------------------------------------


class ReceiptDetailView(PermissionMixin, DetailView):
    permission = "receipts.view"
    model = GoodsReceipt
    template_name = "warehouse/receipt_detail.html"
    context_object_name = "receipt"

    def get_queryset(self):
        return super().get_queryset().select_related("supplier", "purchase_order", "confirmed_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        receipt = self.object
        if receipt.is_draft:
            # Previzualizare: exact ce se va întâmpla la confirmare (aceeași funcție).
            context["preview"] = services.preview_receipt(receipt)
            context["preview_quarantine"] = any(q > 0 for _, _, q in context["preview"])
        else:
            context["lines"] = receipt.lines.select_related(
                "product", "order_line"
            ).prefetch_related("discrepancy")
        return context


class ReceiptConfirmView(PermissionMixin, View):
    permission = "receipts.edit"
    http_method_names = ["post"]

    def post(self, request, pk):
        receipt = get_object_or_404(GoodsReceipt, pk=pk)
        try:
            receipt = services.confirm_receipt(receipt, request.user)
        except services.WarehouseError as error:
            messages.error(request, " ".join(error.messages))
            return redirect(receipt)
        quarantine = Discrepancy.objects.filter(receipt_line__receipt=receipt).count()
        text = f"Recepția {receipt.number} a fost confirmată; marfa acceptată a intrat în stoc."
        if quarantine:
            text += f" {quarantine} linii au mers în carantină; decizia aparține Achizițiilor."
        messages.success(request, text)
        return redirect(receipt)


class ReceiptDeleteView(PermissionMixin, View):
    permission = "receipts.edit"
    http_method_names = ["post"]

    def post(self, request, pk):
        receipt = get_object_or_404(GoodsReceipt, pk=pk)
        try:
            services.delete_draft_receipt(receipt)
        except services.WarehouseError as error:
            messages.error(request, " ".join(error.messages))
            return redirect(receipt)
        messages.success(request, "Ciorna recepției a fost ștearsă.")
        return redirect("warehouse:receipt_list")


# --- Formularul recepției (creare pe comandă / fără comandă, editarea ciornei) -----------------


class ReceiptFormView(PermissionMixin, View):
    permission = "receipts.edit"
    template_name = "warehouse/receipt_form.html"

    def get_receipt(self):
        """Recepția editată: nouă (nesalvată) sau o ciornă existentă. Poate întoarce în
        schimb un răspuns de redirecționare, când recepția nu e posibilă."""
        raise NotImplementedError

    def get(self, request, *args, **kwargs):
        receipt = self.get_receipt()
        if not isinstance(receipt, GoodsReceipt):
            return receipt  # redirecționare (ex. comandă pe care nu se mai poate recepționa)
        return self.render(receipt, ReceiptForm(instance=receipt), self.build_lines(receipt))

    def post(self, request, *args, **kwargs):
        receipt = self.get_receipt()
        if not isinstance(receipt, GoodsReceipt):
            return receipt
        form = ReceiptForm(request.POST, instance=receipt)
        lines = self.build_lines(receipt, request.POST)
        if form.is_valid() and lines.is_valid():
            return self.save(form, lines)
        return self.render(receipt, form, lines)

    def build_lines(self, receipt, data=None):
        """Rândurile: liniile existente + câte un rând pentru fiecare linie a comenzii
        care nu e încă pe recepție, cu cantitatea așteptată afișată alături."""
        pending = {}
        if receipt.purchase_order_id:
            for line in (
                PurchaseOrderLine.objects.with_progress()
                .filter(order=receipt.purchase_order_id)
                .select_related("product")
            ):
                line.remaining_qty = max(line.quantity - line.received_qty, ZERO)
                pending[line.pk] = line
        present = (
            set(receipt.lines.values_list("order_line_id", flat=True)) if receipt.pk else set()
        )
        initial = [
            {"order_line": line.pk, "product": line.product_id}
            # Întâi liniile care mai așteaptă marfă, apoi cele complete (pentru un surplus).
            for line in sorted(pending.values(), key=lambda pl: (pl.remaining_qty == 0, pl.pk))
            if line.pk not in present
        ]
        formset_class = receipt_line_formset(extra=len(initial))
        return formset_class(
            data,
            instance=receipt,
            initial=initial,
            prefix="lines",
            form_kwargs={"pending": pending},
        )

    @transaction.atomic
    def save(self, form, lines):
        receipt = form.save()
        lines.instance = receipt
        lines.save()
        messages.success(
            self.request,
            "Ciorna recepției a fost salvată. Verifică previzualizarea și confirmă recepția.",
        )
        return redirect(receipt)

    def render(self, receipt, form, lines):
        context = {
            "receipt": receipt,
            "form": form,
            "lines": lines,
            "order": receipt.purchase_order,
        }
        return render(self.request, self.template_name, context)


class ReceiptFromOrderView(ReceiptFormView):
    def get_receipt(self):
        order = get_object_or_404(PurchaseOrder, pk=self.kwargs["order_pk"])
        if order.status not in GoodsReceipt.RECEIVABLE_ORDER_STATUSES:
            status = order.get_status_display().lower()
            messages.error(self.request, f"Pe comanda {order} nu se poate recepționa ({status}).")
            return redirect("warehouse:expected")
        return GoodsReceipt(purchase_order=order, supplier=order.supplier)


class ReceiptWithoutOrderView(ReceiptFormView):
    def get_receipt(self):
        return GoodsReceipt()


class ReceiptUpdateView(ReceiptFormView):
    def get_receipt(self):
        receipt = get_object_or_404(GoodsReceipt, pk=self.kwargs["pk"])
        if not receipt.is_draft:
            messages.error(self.request, "O recepție confirmată nu se mai poate modifica.")
            return redirect(receipt)
        return receipt
