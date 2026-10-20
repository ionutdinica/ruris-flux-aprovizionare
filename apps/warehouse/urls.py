from django.urls import path

from . import views

app_name = "warehouse"

# Depozitul are trei zone: recepții, discrepanțe (carantină) și stoc.
urlpatterns = [
    # Recepții
    path("receptii/", views.ReceiptListView.as_view(), name="receipt_list"),
    path("receptii/asteptate/", views.ExpectedDeliveriesView.as_view(), name="expected"),
    path(
        "receptii/noua/comanda/<int:order_pk>/",
        views.ReceiptFromOrderView.as_view(),
        name="receipt_from_order",
    ),
    path(
        "receptii/noua/fara-comanda/",
        views.ReceiptWithoutOrderView.as_view(),
        name="receipt_without_order",
    ),
    path("receptii/<int:pk>/", views.ReceiptDetailView.as_view(), name="receipt_detail"),
    path("receptii/<int:pk>/editare/", views.ReceiptUpdateView.as_view(), name="receipt_update"),
    path("receptii/<int:pk>/confirma/", views.ReceiptConfirmView.as_view(), name="receipt_confirm"),
    path("receptii/<int:pk>/sterge/", views.ReceiptDeleteView.as_view(), name="receipt_delete"),
    # Discrepanțe
    path("discrepante/", views.DiscrepancyListView.as_view(), name="discrepancy_list"),
    path("discrepante/<int:pk>/", views.DiscrepancyDetailView.as_view(), name="discrepancy_detail"),
    path(
        "discrepante/<int:pk>/ataseaza/",
        views.DiscrepancyAttachView.as_view(),
        name="discrepancy_attach",
    ),
    path(
        "discrepante/<int:pk>/accepta-surplus/",
        views.DiscrepancyAcceptSurplusView.as_view(),
        name="discrepancy_accept_surplus",
    ),
    path(
        "discrepante/<int:pk>/returneaza/",
        views.DiscrepancyReturnView.as_view(),
        name="discrepancy_return",
    ),
    # Stoc
    path("stoc/", views.StockListView.as_view(), name="stock"),
    path("stoc/miscare/", views.StockMovementCreateView.as_view(), name="stock_movement"),
    path(
        "stoc/miscare/produs/",
        views.StockMovementProductInfoView.as_view(),
        name="stock_movement_product",
    ),
    path("stoc/<int:pk>/", views.StockProductView.as_view(), name="stock_product"),
]
