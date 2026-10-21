from django import forms

from apps.catalog.models import Supplier
from apps.core.forms import BootstrapFormMixin

from .models import SupplierBudget


class SupplierBudgetForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = SupplierBudget
        fields = ["supplier", "year", "amount", "notes"]
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
        help_texts = {
            "amount": "Fără TVA, în moneda furnizorului (RON sau EUR, ca în contract).",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        budget = self.instance
        suppliers = Supplier.objects.filter(is_active=True)
        if budget.supplier_id:
            suppliers = suppliers | Supplier.objects.filter(pk=budget.supplier_id)
        self.fields["supplier"].queryset = suppliers.distinct().order_by("name")
        if budget.pk:  # un buget existent își schimbă doar suma și observațiile
            for name in ("supplier", "year"):
                self.fields[name].disabled = True
            self.fields["amount"].help_text = f"Fără TVA, în {budget.currency}."
