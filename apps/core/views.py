from functools import reduce
from operator import or_

from django.db.models import Q

from .models import SearchableModel
from .text import fold


class SearchListMixin:
    """Liste cu căutare, filtru activ/inactiv și paginare, reutilizabile.

        class SupplierListView(PermissionMixin, SearchListMixin, ListView):
            model = Supplier
            partial_template_name = "catalog/partials/supplier_table.html"

    Căutarea folosește `search_text` pentru modelele SearchableModel (fără diacritice),
    altfel câmpurile din `search_fields` ale view-ului.
    Parametri din adresă: ?q=text&status=active|inactive&page=2
    Cererile HTMX primesc doar tabelul (`partial_template_name`), nu toată pagina.
    """

    search_fields = []
    partial_template_name = None
    paginate_by = 20

    STATUS_CHOICES = [("", "Toate"), ("active", "Active"), ("inactive", "Inactive")]

    def get_queryset(self):
        queryset = super().get_queryset()
        query = self.request.GET.get("q", "").strip()
        if query and issubclass(queryset.model, SearchableModel):
            # Căutare fără diacritice: „otel” găsește „Oțelăria” (vezi SearchableModel).
            queryset = queryset.filter(search_text__contains=fold(query))
        elif query and self.search_fields:
            # Caută textul în oricare dintre câmpuri: nume SAU cod SAU email...
            conditions = [Q(**{f"{field}__icontains": query}) for field in self.search_fields]
            queryset = queryset.filter(reduce(or_, conditions))

        status = self.request.GET.get("status", "")
        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)
        return queryset

    def get_template_names(self):
        if self.request.headers.get("HX-Request") and self.partial_template_name:
            return [self.partial_template_name]
        return super().get_template_names()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            query=self.request.GET.get("q", ""),
            status=self.request.GET.get("status", ""),
            status_choices=self.STATUS_CHOICES,
        )
        return context
