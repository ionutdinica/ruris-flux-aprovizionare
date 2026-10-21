from django.urls import path

from . import views

app_name = "invoicing"

urlpatterns = [
    path("", views.InvoiceListView.as_view(), name="invoice_list"),
    path("noua/", views.InvoiceCreateView.as_view(), name="invoice_create"),
    path("linii-comanda/", views.OrderLineOptionsView.as_view(), name="order_line_options"),
    path("<int:pk>/", views.InvoiceDetailView.as_view(), name="invoice_detail"),
    path("<int:pk>/editare/", views.InvoiceUpdateView.as_view(), name="invoice_update"),
    path("<int:pk>/valideaza/", views.InvoiceValidateView.as_view(), name="invoice_validate"),
    path("<int:pk>/redeschide/", views.InvoiceReopenView.as_view(), name="invoice_reopen"),
    path("<int:pk>/aproba/", views.InvoiceApproveView.as_view(), name="invoice_approve"),
    path("<int:pk>/forteaza/", views.InvoiceForceApproveView.as_view(), name="invoice_force"),
    path("<int:pk>/plateste/", views.InvoicePayView.as_view(), name="invoice_pay"),
    path("<int:pk>/respinge/", views.InvoiceRejectView.as_view(), name="invoice_reject"),
]
