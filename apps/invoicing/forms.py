"""Formularele facturii: antetul + liniile (un formset, ca la comenzi).

Fiecare linie de factură se leagă de o linie de comandă a furnizorului ales. Lista
liniilor disponibile se schimbă când se schimbă furnizorul (static/js/invoice_form.js
o reîncarcă de la server); la salvare, serverul verifică din nou că linia e permisă.
"""

from django import forms
from django.core.exceptions import ValidationError

from apps.catalog.models import Supplier
from apps.core.forms import BootstrapFormMixin, DateInput
from apps.core.text import format_quantity
from apps.purchasing.forms import SupplierSelect
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine

from .models import Invoice, InvoiceLine


def invoiceable_order_lines(supplier_id, include=()):
    """Liniile de comandă care pot apărea pe o factură a furnizorului: din comenzi
    trimise (inclusiv recepționate sau închise), nu din ciorne sau comenzi anulate.

    `include` = linii deja aflate pe factură, păstrate chiar dacă între timp comanda
    a fost anulată (potrivirea va semnala problema, nu formularul o va ascunde).
    """
    eligible = PurchaseOrderLine.objects.filter(order__supplier_id=supplier_id).exclude(
        order__status__in=[PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.CANCELLED]
    )
    if include:
        eligible = eligible | PurchaseOrderLine.objects.filter(pk__in=include)
    return (
        PurchaseOrderLine.objects.with_progress()
        .filter(pk__in=eligible.values("pk"))
        .select_related("order", "product")
        .order_by("-order__order_date", "-order__number", "id")
    )


def order_line_label(line):
    q = format_quantity
    unit = line.product.unit
    return (
        f"{line.order.number} · {line.product.code} {line.product.name} · comandat "
        f"{q(line.quantity)} {unit}, recepționat {q(line.received_qty)}, facturat "
        f"{q(line.invoiced_qty)}"
    )


class OrderLineSelect(forms.Select):
    """Opțiunile poartă datele necesare completării automate a liniei de factură:
    prețul și TVA din comandă, moneda și cantitatea rămasă de facturat."""

    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        line = getattr(value, "instance", None)
        if line is not None:
            remaining = max(line.received_qty - line.invoiced_qty, 0)
            option["attrs"].update(
                {
                    "data-price": format_quantity(line.unit_price),
                    "data-vat": f"{line.vat_rate:.2f}",
                    "data-currency": line.order.currency,
                    "data-remaining": format_quantity(remaining),
                }
            )
        return option


class OrderLineChoiceField(forms.ModelChoiceField):
    widget = OrderLineSelect

    def label_from_instance(self, obj):
        return order_line_label(obj)


class InvoiceForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Invoice
        fields = [
            "supplier",
            "supplier_invoice_number",
            "currency",
            "invoice_date",
            "due_date",
            "declared_net",
            "declared_vat",
            "declared_total",
            "notes",
        ]
        widgets = {
            "supplier": SupplierSelect,
            "invoice_date": DateInput,
            "due_date": DateInput,
            "declared_net": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "declared_vat": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "declared_total": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
        help_texts = {
            "declared_total": "Exact cum apare pe factura primită; se compară cu liniile.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        suppliers = Supplier.objects.filter(is_active=True)
        if self.instance.supplier_id:
            suppliers = suppliers | Supplier.objects.filter(pk=self.instance.supplier_id)
        self.fields["supplier"].queryset = suppliers.distinct()


class InvoiceLineForm(BootstrapFormMixin, forms.ModelForm):
    order_line = OrderLineChoiceField(
        queryset=PurchaseOrderLine.objects.none(), label="Linie de comandă"
    )

    class Meta:
        model = InvoiceLine
        fields = ["order_line", "quantity", "unit_price", "vat_rate"]
        widgets = {
            "quantity": forms.NumberInput(attrs={"step": "0.001", "min": "0"}),
            "unit_price": forms.NumberInput(attrs={"step": "0.0001", "min": "0"}),
        }

    def __init__(self, *args, order_lines=None, **kwargs):
        super().__init__(*args, **kwargs)
        if order_lines is not None:
            self.fields["order_line"].queryset = order_lines
        if self.instance.pk:
            for name in ("quantity", "unit_price"):
                self.initial[name] = format_quantity(getattr(self.instance, name))


class BaseInvoiceLineFormSet(forms.BaseInlineFormSet):
    """Toate liniile primesc aceeași listă de linii de comandă: cele ale furnizorului."""

    def __init__(self, *args, supplier_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        include = []
        if self.instance.pk:
            include = list(self.instance.lines.values_list("order_line_id", flat=True))
        self.order_lines = (
            invoiceable_order_lines(supplier_id, include)
            if supplier_id
            else (PurchaseOrderLine.objects.none())
        )

    def get_form_kwargs(self, index):
        # Folosit și pentru rândul-model al liniilor noi (empty_form, index None).
        return {**super().get_form_kwargs(index), "order_lines": self.order_lines}

    def clean(self):
        super().clean()
        remaining = [
            form for form in self.forms if form.cleaned_data and not self._should_delete_form(form)
        ]
        if not remaining:
            raise ValidationError("Factura trebuie să aibă cel puțin o linie.")


InvoiceLineFormSet = forms.inlineformset_factory(
    Invoice,
    InvoiceLine,
    form=InvoiceLineForm,
    formset=BaseInvoiceLineFormSet,
    extra=0,
    can_delete=True,
)
