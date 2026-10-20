"""Formularele depozitului.

Recepția are două feluri de rânduri:
  - rânduri de pe comandă: produsul și linia de comandă sunt fixe (nu pot fi schimbate
    din browser); se completează doar cantitatea NUMĂRATĂ;
  - rânduri în plus: produse sosite fără să fie pe comandă; merg integral în carantină.
"""

from decimal import Decimal

from django import forms
from django.urls import reverse

from apps.catalog.models import Product, Supplier
from apps.core.forms import BootstrapFormMixin, DateInput

from .models import GoodsReceipt, GoodsReceiptLine

ZERO = Decimal("0")


class ReceiptForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = GoodsReceipt
        fields = ["supplier", "receipt_date", "delivery_note", "notes"]
        widgets = {
            "receipt_date": DateInput,
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.purchase_order_id:
            del self.fields["supplier"]  # furnizorul vine din comandă
        else:
            suppliers = Supplier.objects.active()
            if self.instance.supplier_id:
                suppliers = suppliers | Supplier.objects.filter(pk=self.instance.supplier_id)
            self.fields["supplier"].queryset = suppliers.distinct()


class ReceiptLineForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = GoodsReceiptLine
        fields = ["product", "order_line", "quantity_received", "notes"]
        widgets = {
            "order_line": forms.HiddenInput,
            "quantity_received": forms.NumberInput(attrs={"step": "0.001", "min": "0"}),
        }

    def __init__(self, *args, pending=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Linia de comandă nu vine niciodată din browser: doar din recepție (disabled).
        self.fields["order_line"].disabled = True
        order_line_id = self.initial.get("order_line") or self.instance.order_line_id
        self.pending = (pending or {}).get(int(order_line_id)) if order_line_id else None

        if self.pending is not None:
            # Rând de pe comandă: produsul e fix; câmp gol = „nu a venit” (0).
            self.fields["product"].disabled = True
            self.fields["product"].queryset = Product.objects.all()
            self.fields["quantity_received"].required = False
        else:
            products = Product.objects.active()
            if self.instance.product_id:
                products = products | Product.objects.filter(pk=self.instance.product_id)
            self.fields["product"].queryset = products.distinct()

    @property
    def is_order_row(self):
        return self.pending is not None

    def clean_quantity_received(self):
        quantity = self.cleaned_data.get("quantity_received")
        if quantity is None and self.is_order_row:
            return ZERO
        return quantity


class BaseReceiptLineFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        order = self.instance.purchase_order if self.instance.purchase_order_id else None
        if order is None:
            return
        ordered_products = set(order.lines.values_list("product_id", flat=True))
        for form in self.forms:
            if form.is_order_row or self._should_delete_form(form) or not form.has_changed():
                continue
            product = form.cleaned_data.get("product")
            if product and product.pk in ordered_products:
                form.add_error(
                    "product",
                    "Produsul este pe comandă: completează cantitatea pe linia lui.",
                )


def receipt_line_formset(extra):
    """Formset-ul liniilor; `extra` = rândurile de pe comandă care nu sunt încă pe recepție."""
    return forms.inlineformset_factory(
        GoodsReceipt,
        GoodsReceiptLine,
        form=ReceiptLineForm,
        formset=BaseReceiptLineFormSet,
        extra=extra,
        can_delete=True,
    )


# --- Discrepanțe (decizia Achizițiilor) ----------------------------------------------------


class OrderLineChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, line):
        return f"{line.order} · termen {line.expected_date:%d.%m.%Y}"


class AttachDiscrepancyForm(BootstrapFormMixin, forms.Form):
    """Alegerea liniei de comandă: doar dintre liniile potrivite (services.attach_candidates)."""

    order_line = OrderLineChoiceField(
        label="Linia de comandă", queryset=None, widget=forms.RadioSelect, empty_label=None
    )
    note = forms.CharField(label="Observații", required=False, max_length=500)

    def __init__(self, *args, candidates, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order_line"].queryset = candidates


class NoteForm(BootstrapFormMixin, forms.Form):
    note = forms.CharField(label="Observații", required=False, max_length=500)


class ReturnDiscrepancyForm(BootstrapFormMixin, forms.Form):
    note = forms.CharField(
        label="Motivul returului",
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Ex. „Marfă necomandată, returnată cu avizul 1234”.",
    )


# --- Ieșiri și ajustări de stoc -----------------------------------------------------------------


class StockMovementForm(BootstrapFormMixin, forms.Form):
    KIND_CHOICES = [
        ("CONSUMPTION", "Consum (ieșire în producție / vânzare)"),
        ("SUPPLIER_RETURN", "Retur la furnizor (ieșire)"),
        ("ADJUSTMENT_PLUS", "Ajustare de inventar: plus (s-a găsit mai mult)"),
        ("ADJUSTMENT_MINUS", "Ajustare de inventar: minus (lipsă la numărare)"),
    ]

    product = forms.ModelChoiceField(label="Produs", queryset=Product.objects.order_by("code"))
    kind = forms.ChoiceField(label="Tip", choices=KIND_CHOICES)
    quantity = forms.DecimalField(
        label="Cantitate",
        min_value=Decimal("0.001"),
        max_digits=12,
        decimal_places=3,
        widget=forms.NumberInput(attrs={"step": "0.001", "min": "0"}),
    )
    date = forms.DateField(label="Data", widget=DateInput)
    order_line = forms.ModelChoiceField(
        label="Linia de comandă returnată (opțional)",
        queryset=None,
        required=False,
        help_text="Doar pentru retur: comanda redevine „parțial recepționată”, furnizorul "
        "datorează din nou marfa.",
    )
    reason = forms.CharField(
        label="Motiv",
        max_length=200,
        help_text="Obligatoriu. Ex. „Consum comanda de producție 45”, „Inventar lunar”.",
    )

    def __init__(self, *args, returnable_lines, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order_line"].queryset = returnable_lines
        # La alegerea produsului, HTMX cere stocul lui și liniile returnabile (fără reîncărcare).
        self.fields["product"].widget.attrs.update(
            {
                "hx-get": reverse("warehouse:stock_movement_product"),
                "hx-target": "#product-dependent",
                "hx-swap": "outerHTML",
            }
        )
