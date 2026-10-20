from django import forms

from apps.core.forms import BootstrapFormMixin

from .models import Product, Supplier


class SupplierForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Supplier
        fields = [
            "name",
            "country",
            "tax_id",
            "email",
            "phone",
            "address",
            "default_currency",
            "is_active",
        ]
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}
        help_texts = {"is_active": "Furnizorii inactivi nu mai pot fi aleși pe comenzi noi."}


class ProductForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ["code", "name", "unit", "vat_rate", "description", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}
        help_texts = {"is_active": "Produsele inactive nu mai pot fi alese pe documente noi."}
