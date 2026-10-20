from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.views.generic import TemplateView

from apps.accounts.permissions import PermissionMixin

from .forms import ActivityFilterForm
from .timeline import TimelineFilters, hydrate, timeline_rows

PAGE_SIZE = 25


class ActivityLogView(PermissionMixin, TemplateView):
    """Jurnalul de activitate: modificări de date și evenimente, într-o singură cronologie."""

    permission = "audit.view"
    template_name = "audit/activity_log.html"

    def get_template_names(self):
        # Cererile HTMX (schimbarea unui filtru, paginarea) primesc doar zona de
        # rezultate, nu toată pagina: se actualizează fără reîncărcare.
        if self.request.headers.get("HX-Request"):
            return ["audit/partials/activity_results.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = ActivityFilterForm(self.request.GET or None)
        filters = self._filters(form)

        page = Paginator(timeline_rows(filters), PAGE_SIZE).get_page(self.request.GET.get("page"))
        context.update(
            form=form,
            page=page,
            entries=hydrate(page.object_list),  # detalii doar pentru pagina curentă
            document=self._document(filters),
        )
        return context

    @staticmethod
    def _filters(form):
        if not form.is_bound or not form.is_valid():
            return TimelineFilters()  # filtre invalide: se afișează tot, cu erorile în formular
        data = form.cleaned_data
        return TimelineFilters(
            actor_id=data["actor"].pk if data["actor"] else None,
            kind=data["kind"],
            date_from=data["date_from"],
            date_to=data["date_to"],
            content_type_id=data["ct"],
            object_id=data["obj"] or "",
        )

    @staticmethod
    def _document(filters):
        """Dacă se afișează istoricul unui singur document, care e acela."""
        if not filters.content_type_id:
            return None
        content_type = ContentType.objects.filter(pk=filters.content_type_id).first()
        if content_type is None:
            return None
        model = content_type.model_class()
        obj = model._default_manager.filter(pk=filters.object_id).first() if model else None
        return obj or f"{content_type.name} #{filters.object_id}"
