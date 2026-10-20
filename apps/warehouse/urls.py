from django.urls import path

from . import views

app_name = "warehouse"

urlpatterns = [
    path("", views.ReceiptListView.as_view(), name="receipt_list"),
    path("asteptate/", views.ExpectedDeliveriesView.as_view(), name="expected"),
    path(
        "noua/comanda/<int:order_pk>/",
        views.ReceiptFromOrderView.as_view(),
        name="receipt_from_order",
    ),
    path(
        "noua/fara-comanda/", views.ReceiptWithoutOrderView.as_view(), name="receipt_without_order"
    ),
    path("<int:pk>/", views.ReceiptDetailView.as_view(), name="receipt_detail"),
    path("<int:pk>/editare/", views.ReceiptUpdateView.as_view(), name="receipt_update"),
    path("<int:pk>/confirma/", views.ReceiptConfirmView.as_view(), name="receipt_confirm"),
    path("<int:pk>/sterge/", views.ReceiptDeleteView.as_view(), name="receipt_delete"),
]
