"""Paginile bugetelor. Achizițiile și Contabilitatea le văd (budgets.view); doar
Contabilitatea și Admin le stabilesc (budgets.edit) – vezi docs/04-permisiuni.md.

Nu există ștergere: un buget greșit se corectează (suma), iar modificarea rămâne în jurnal.
"""

from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, TemplateView, UpdateView

from apps.accounts.permissions import PermissionMixin
from apps.catalog.models import Supplier
from apps.core.templatetags.formatting import money

from . import services
from .forms import SupplierBudgetForm
from .models import SupplierBudget


def _year(value, default):
    return int(value) if value.isdigit() and 2000 <= int(value) <= 2100 else default


class BudgetListView(PermissionMixin, TemplateView):
    permission = "budgets.view"
    template_name = "budgets/budget_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current = timezone.localdate().year
        year = _year(self.request.GET.get("an", ""), current)
        rows = services.statuses(year)
        years = set(SupplierBudget.objects.values_list("year", flat=True))
        years |= {current, current + 1, year}
        budgeted = [row.budget.supplier_id for row in rows]
        context.update(
            year=year,
            years=sorted(years, reverse=True),
            rows=rows,
            without_budget=Supplier.objects.filter(is_active=True)
            .exclude(pk__in=budgeted)
            .order_by("name"),
        )
        return context


class BudgetFormMixin(PermissionMixin, SuccessMessageMixin):
    permission = "budgets.edit"
    model = SupplierBudget
    form_class = SupplierBudgetForm
    template_name = "core/form_page.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(list_url=reverse_lazy("budgets:budget_list"), list_label="Bugete")
        return context

    def get_success_url(self):
        return self.object.get_absolute_url()

    def get_success_message(self, cleaned_data):
        budget = self.object
        return f"{budget} a fost salvat: {money(budget.amount)} {budget.currency}, fără TVA."


class BudgetCreateView(BudgetFormMixin, CreateView):
    extra_context = {"page_title": "Buget nou"}

    def get_initial(self):
        """Din pagina de bugete: anul afișat și, opțional, furnizorul (?an=…&furnizor=…)."""
        initial = super().get_initial()
        initial["year"] = _year(self.request.GET.get("an", ""), timezone.localdate().year)
        supplier = self.request.GET.get("furnizor", "")
        if supplier.isdigit():
            initial["supplier"] = supplier
        return initial


class BudgetUpdateView(BudgetFormMixin, UpdateView):
    extra_context = {"page_title": "Editare buget"}
