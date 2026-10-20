"""Formularele comenzii: antetul + liniile (un „formset”: mai multe formulare
de același tip pe o singură pagină, câte unul pentru fiecare linie).

Ce se poate modifica depinde de status (docs/03-fluxuri-si-stari.md, I-07):
  - Ciornă: tot;
  - Trimisă / Parțial recepționată: termene, responsabil, observații, linii noi,
    cantități mai mari; furnizorul, moneda, produsele, prețurile și TVA sunt blocate,
    iar liniile existente nu se pot șterge.
"""

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

from apps.accounts.models import User
from apps.catalog.models import Product, Supplier
from apps.core.forms import BootstrapFormMixin
from apps.core.text import format_quantity

from .models import PurchaseOrder, PurchaseOrderLine


class SupplierSelect(forms.Select):
    """Lista de furnizori cu moneda implicită atașată fiecărei opțiuni
    (data-currency), ca formularul să propună moneda la alegerea furnizorului."""

    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        if value and hasattr(value, "instance"):
            option["attrs"]["data-currency"] = value.instance.default_currency
        return option


class ProductSelect(forms.Select):
    """Lista de produse cu cota TVA și UM atașate (data-vat, data-unit)."""

    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        if value and hasattr(value, "instance"):
            option["attrs"]["data-vat"] = f"{value.instance.vat_rate:.2f}"
            option["attrs"]["data-unit"] = value.instance.unit
        return option


class PurchaseOrderForm(BootstrapFormMixin, forms.ModelForm):
    LOCKED_AFTER_SENDING = ("supplier", "currency", "order_date")

    class Meta:
        model = PurchaseOrder
        fields = [
            "supplier",
            "currency",
            "owner",
            "order_date",
            "expected_date",
            "external_reference",
            "notes",
        ]
        widgets = {
            "supplier": SupplierSelect,
            "order_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "expected_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        order = self.instance
        # Furnizori: doar cei activi (plus cel deja ales, dacă între timp a fost dezactivat).
        suppliers = Supplier.objects.filter(is_active=True)
        if order.supplier_id:
            suppliers = suppliers | Supplier.objects.filter(pk=order.supplier_id)
        self.fields["supplier"].queryset = suppliers.distinct()
        # Responsabil: doar cei care pot gestiona comenzi.
        self.fields["owner"].queryset = User.objects.filter(
            is_active=True, role__in=[User.Role.PROCUREMENT, User.Role.ADMIN]
        ).order_by("first_name", "last_name")

        if order.pk and order.is_amendable:
            for name in self.LOCKED_AFTER_SENDING:
                self.fields[name].disabled = True  # valoarea vine din comandă, nu din formular
                self.fields[name].help_text = "Nu se mai poate modifica după trimitere."


class PurchaseOrderLineForm(BootstrapFormMixin, forms.ModelForm):
    LOCKED_AFTER_SENDING = ("product", "unit_price", "vat_rate")

    class Meta:
        model = PurchaseOrderLine
        fields = ["product", "quantity", "unit_price", "vat_rate", "expected_date"]
        widgets = {
            "product": ProductSelect,
            "quantity": forms.NumberInput(attrs={"step": "0.001", "min": "0"}),
            "unit_price": forms.NumberInput(attrs={"step": "0.0001", "min": "0"}),
            "expected_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        line = self.instance
        products = Product.objects.filter(is_active=True)
        if line.product_id:
            products = products | Product.objects.filter(pk=line.product_id)
        self.fields["product"].queryset = products.distinct()
        # Termenul liniei e opțional în formular: implicit, cel din antetul comenzii.
        self.fields["expected_date"].required = False
        # Fără zerouri inutile în câmpuri: „12”, nu „12.000”; „89.9”, nu „89.9000”.
        if line.pk:
            for name in ("quantity", "unit_price"):
                self.initial[name] = format_quantity(getattr(line, name))

        if line.pk and line.order.is_amendable:
            for name in self.LOCKED_AFTER_SENDING:
                self.fields[name].disabled = True
            self.fields["quantity"].widget.attrs["min"] = f"{line.quantity:f}"


class BaseLineFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        order = self.instance
        if order.pk and order.is_amendable:
            for form in self.forms:
                if form.instance.pk and self._should_delete_form(form):
                    raise ValidationError(
                        "Liniile unei comenzi trimise nu se pot șterge; "
                        "doar cantitatea poate crește."
                    )

    def save(self, commit=True):
        # Liniile fără termen propriu primesc termenul din antetul comenzii.
        for form in self.forms:
            if form.has_changed() and not form.cleaned_data.get("expected_date"):
                form.instance.expected_date = self.instance.expected_date
        return super().save(commit)


PurchaseOrderLineFormSet = forms.inlineformset_factory(
    PurchaseOrder,
    PurchaseOrderLine,
    form=PurchaseOrderLineForm,
    formset=BaseLineFormSet,
    extra=0,
    can_delete=True,
)


class ReasonForm(BootstrapFormMixin, forms.Form):
    """Motivul anulării / închiderii cu rest (obligatoriu, intră în jurnal)."""

    reason = forms.CharField(label="Motiv", widget=forms.Textarea(attrs={"rows": 3}))


class ImportFileForm(BootstrapFormMixin, forms.Form):
    """Încărcarea fișierului Excel cu comenzi (pasul 1 al importului)."""

    MAX_SIZE = 5 * 1024 * 1024  # 5 MB

    file = forms.FileField(
        label="Fișier Excel (.xlsx)",
        validators=[FileExtensionValidator(["xlsx"], "Sunt acceptate doar fișiere Excel .xlsx.")],
        widget=forms.FileInput(attrs={"accept": ".xlsx"}),
    )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if uploaded.size > self.MAX_SIZE:
            raise ValidationError("Fișierul depășește 5 MB.")
        return uploaded
