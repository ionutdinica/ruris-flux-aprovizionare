"""Paginile nomenclatoarelor. Toți văd (catalog.view), doar Achizițiile și
Admin adaugă / modifică (catalog.edit) – vezi docs/04-permisiuni.md.

Nu există pagini de ștergere: furnizorii și produsele se dezactivează.
"""

from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.accounts.permissions import PermissionMixin
from apps.core.views import SearchListMixin

from .forms import ProductForm, SupplierForm
from .models import Product, Supplier


class CatalogFormMixin(PermissionMixin, SuccessMessageMixin):
    """Comun formularelor de adăugare / editare: permisiune, mesaj, pagina generică."""

    permission = "catalog.edit"
    template_name = "core/form_page.html"
    list_url = None
    list_label = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(list_url=self.list_url, list_label=self.list_label)
        return context


# --- Furnizori --------------------------------------------------------------------


class SupplierListView(PermissionMixin, SearchListMixin, ListView):
    permission = "catalog.view"
    model = Supplier
    partial_template_name = "catalog/partials/supplier_table.html"


class SupplierDetailView(PermissionMixin, DetailView):
    permission = "catalog.view"
    model = Supplier

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.can("budgets.view"):
            from apps.budgets.services import status_for  # bugetele depind de catalog

            context["year"] = timezone.localdate().year
            context["budget"] = status_for(self.object, context["year"])
        return context


class SupplierFormMixin(CatalogFormMixin):
    model = Supplier
    form_class = SupplierForm
    list_url = reverse_lazy("catalog:supplier_list")
    list_label = "Furnizori"


class SupplierCreateView(SupplierFormMixin, CreateView):
    success_message = "Furnizorul „%(name)s” a fost adăugat."
    extra_context = {"page_title": "Furnizor nou"}


class SupplierUpdateView(SupplierFormMixin, UpdateView):
    success_message = "Modificările la „%(name)s” au fost salvate."
    extra_context = {"page_title": "Editare furnizor"}


# --- Produse ----------------------------------------------------------------------


class ProductListView(PermissionMixin, SearchListMixin, ListView):
    permission = "catalog.view"
    model = Product
    partial_template_name = "catalog/partials/product_table.html"


class ProductDetailView(PermissionMixin, DetailView):
    permission = "catalog.view"
    model = Product


class ProductFormMixin(CatalogFormMixin):
    model = Product
    form_class = ProductForm
    list_url = reverse_lazy("catalog:product_list")
    list_label = "Produse"


class ProductCreateView(ProductFormMixin, CreateView):
    success_message = "Produsul „%(code)s – %(name)s” a fost adăugat."
    extra_context = {"page_title": "Produs nou"}


class ProductUpdateView(ProductFormMixin, UpdateView):
    success_message = "Modificările la „%(code)s – %(name)s” au fost salvate."
    extra_context = {"page_title": "Editare produs"}
