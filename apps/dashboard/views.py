from django.views.generic import TemplateView


class HomeView(TemplateView):
    """Pagina de start. Provizorie: în capitolul 9 devine panoul de control pe rol."""

    template_name = "dashboard/home.html"
