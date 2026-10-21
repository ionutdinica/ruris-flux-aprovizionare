"""Paginile depozitului. Vizualizare: toate rolurile (receipts.view); recepția,
confirmarea și ștergerea ciornelor: Depozit și Admin (receipts.edit).
Nicio pagină de aici nu afișează prețuri."""

from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, FormView, ListView

from apps.accounts.permissions import PermissionMixin
from apps.catalog.models import Product
from apps.core.text import format_quantity
from apps.core.views import SearchListMixin
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine

from . import services
from .forms import (
    AttachDiscrepancyForm,
    NoteForm,
    ReceiptForm,
    ReturnDiscrepancyForm,
    StockMovementForm,
    receipt_line_formset,
)
from .models import Discrepancy, GoodsReceipt
from .selectors import (
    available_stock,
    expected_deliveries,
    products_with_stock,
    quarantined_stock,
    returnable_order_lines,
    stock_ledger,
)

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
            # O comandă poate avea o linie întârziată ȘI alta așteptată azi: contează și ea.
            due_today = PurchaseOrderLine.objects.with_progress().filter(
                order=OuterRef("pk"), expected_date=today, received_qty__lt=F("quantity")
            )
            return queryset.filter(Exists(due_today))
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


# --- Discrepanțe (marfa din carantină) -----------------------------------------------------------


class DiscrepancyListView(PermissionMixin, SearchListMixin, ListView):
    permission = "discrepancies.view"
    model = Discrepancy
    template_name = "warehouse/discrepancy_list.html"
    partial_template_name = "warehouse/partials/discrepancy_table.html"
    search_fields = [
        "receipt_line__product__search_text",
        "receipt_line__receipt__supplier__search_text",
        "receipt_line__receipt__search_text",
    ]
    status_choices = [
        ("", "Toate"),
        (Discrepancy.Status.OPEN, "Deschise (așteaptă decizia)"),
        (Discrepancy.Status.RESOLVED, "Rezolvate"),
        (Discrepancy.Type.OVER_DELIVERY, "Livrări peste comandă"),
        (Discrepancy.Type.UNORDERED, "Marfă necomandată"),
    ]

    def base_queryset(self):
        return (
            super()
            .base_queryset()
            .select_related(
                "receipt_line__product",
                "receipt_line__receipt__supplier",
                "receipt_line__receipt__purchase_order",
                "resolved_by",
            )
            .order_by("status", "-created_at")  # „OPEN” < „RESOLVED”: deschisele primele
        )

    def filter_status(self, queryset, status):
        if status in Discrepancy.Status.values:
            return queryset.filter(status=status)
        if status in Discrepancy.Type.values:
            return queryset.filter(type=status)
        return queryset

    def filter_mine(self, queryset, user):
        """Ca la email: marfa de pe comenzile mele, plus marfa venită fără comandă (care
        privește toate Achizițiile, neavând un responsabil)."""
        line, receipt = "receipt_line__order_line", "receipt_line__receipt__purchase_order"
        return queryset.filter(
            Q(**{f"{line}__order__owner": user})
            | Q(**{f"{line}__isnull": True, f"{receipt}__owner": user})
            | Q(**{f"{line}__isnull": True, f"{receipt}__isnull": True})
        )


class DiscrepancyDetailView(PermissionMixin, DetailView):
    permission = "discrepancies.view"
    model = Discrepancy
    template_name = "warehouse/discrepancy_detail.html"
    context_object_name = "discrepancy"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related(
                "receipt_line__product",
                "receipt_line__order_line__order",
                "receipt_line__receipt__supplier",
                "receipt_line__receipt__purchase_order",
                "attached_order_line__order",
                "resolved_by",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        discrepancy = self.object
        if discrepancy.is_open and self.request.user.can("discrepancies.resolve"):
            candidates = services.attach_candidates(discrepancy)
            context.update(
                candidates=candidates,
                attach_form=AttachDiscrepancyForm(candidates=candidates),
                note_form=NoteForm(),
                return_form=ReturnDiscrepancyForm(),
            )
            surplus_line = discrepancy.receipt_line.order_line
            if (
                discrepancy.type == Discrepancy.Type.OVER_DELIVERY
                and surplus_line.order.is_amendable
            ):
                context["surplus_line"] = surplus_line
                context["surplus_new_quantity"] = surplus_line.quantity + discrepancy.quantity
        return context


class DiscrepancyActionView(PermissionMixin, View):
    """O decizie asupra mărfii din carantină (POST). Erorile de business devin mesaje."""

    permission = "discrepancies.resolve"
    http_method_names = ["post"]

    def post(self, request, pk):
        discrepancy = get_object_or_404(Discrepancy, pk=pk)
        try:
            messages.success(request, self.act(discrepancy))
        except services.WarehouseError as error:
            messages.error(request, " ".join(error.messages))
        return redirect(discrepancy)

    def act(self, discrepancy):
        raise NotImplementedError


class DiscrepancyAttachView(DiscrepancyActionView):
    def act(self, discrepancy):
        form = AttachDiscrepancyForm(
            self.request.POST, candidates=services.attach_candidates(discrepancy)
        )
        if not form.is_valid():
            raise services.WarehouseError("Alege una dintre liniile de comandă propuse.")
        line = form.cleaned_data["order_line"]
        services.attach_discrepancy(discrepancy, line, self.request.user, form.cleaned_data["note"])
        return f"Marfa a intrat în stoc și a fost atașată comenzii {line.order}."


class DiscrepancyAcceptSurplusView(DiscrepancyActionView):
    def act(self, discrepancy):
        form = NoteForm(self.request.POST)
        note = form.cleaned_data["note"] if form.is_valid() else ""
        services.accept_over_delivery(discrepancy, self.request.user, note)
        return (
            "Surplusul a fost acceptat: cantitatea comandată a crescut, iar marfa a intrat în stoc."
        )


class DiscrepancyReturnView(DiscrepancyActionView):
    def act(self, discrepancy):
        form = ReturnDiscrepancyForm(self.request.POST)
        note = form.cleaned_data["note"] if form.is_valid() else ""
        services.return_discrepancy(discrepancy, self.request.user, note)
        return "Marfa a fost marcată pentru retur la furnizor; nu intră în stoc."


# --- Stoc ---------------------------------------------------------------------------------


class StockListView(PermissionMixin, SearchListMixin, ListView):
    permission = "stock.view"
    model = Product
    template_name = "warehouse/stock_list.html"
    partial_template_name = "warehouse/partials/stock_table.html"
    status_choices = [
        ("", "Toate produsele"),
        ("available", "Cu stoc disponibil"),
        ("quarantine", "Cu marfă în carantină"),
        ("empty", "Fără stoc"),
    ]

    def base_queryset(self):
        return products_with_stock(super().base_queryset()).order_by("code")

    def filter_status(self, queryset, status):
        if status == "available":
            return queryset.filter(stock_available__gt=0)
        if status == "quarantine":
            return queryset.filter(stock_quarantined__gt=0)
        if status == "empty":
            return queryset.filter(stock_available=0)
        return queryset


class StockProductView(PermissionMixin, DetailView):
    """Stocul unui produs și registrul lui complet de mișcări, cu soldul după fiecare."""

    permission = "stock.view"
    model = Product
    template_name = "warehouse/stock_product.html"
    context_object_name = "product"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        product = self.object
        context.update(
            available=available_stock(product),
            quarantined=quarantined_stock(product),
            open_discrepancies=Discrepancy.objects.filter(
                receipt_line__product=product, status=Discrepancy.Status.OPEN
            ).select_related("receipt_line__receipt__supplier"),
            page=Paginator(stock_ledger(product), 25).get_page(self.request.GET.get("page")),
        )
        return context


class StockMovementCreateView(PermissionMixin, FormView):
    """Consum, retur la furnizor sau ajustare de inventar (Depozit)."""

    permission = "stock.move"
    template_name = "warehouse/stock_movement_form.html"
    form_class = StockMovementForm

    def selected_product(self):
        product_id = self.request.POST.get("product") or self.request.GET.get("produs")
        if product_id and str(product_id).isdigit():
            return Product.objects.filter(pk=product_id).first()
        return None

    def get_initial(self):
        return {"product": self.selected_product(), "date": timezone.localdate()}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["returnable_lines"] = returnable_order_lines(self.selected_product())
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        product = self.selected_product()
        if product:
            context.update(product=product, available=available_stock(product))
        return context

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            movement = services.record_stock_movement(
                data["product"],
                data["kind"],
                data["quantity"],
                self.request.user,
                data["reason"],
                order_line=data["order_line"],
                date=data["date"],
            )
        except services.WarehouseError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(
            self.request,
            f"Mișcarea a fost înregistrată: {movement.get_type_display().lower()} "
            f"{format_quantity(movement.quantity, sign=True)} {movement.product.unit}.",
        )
        return redirect("warehouse:stock_product", pk=movement.product_id)


class StockMovementProductInfoView(PermissionMixin, View):
    """Fragment HTMX: la schimbarea produsului în formular, stocul lui disponibil și
    liniile de comandă pe care se poate face un retur."""

    permission = "stock.move"

    def get(self, request):
        product_id = request.GET.get("product", "")
        product = Product.objects.filter(pk=product_id).first() if product_id.isdigit() else None
        form = StockMovementForm(returnable_lines=returnable_order_lines(product))
        context = {"form": form, "product": product}
        if product:
            context["available"] = available_stock(product)
        return render(request, "warehouse/partials/movement_product_info.html", context)
