from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("furnizori/", views.SupplierListView.as_view(), name="supplier_list"),
    path("furnizori/nou/", views.SupplierCreateView.as_view(), name="supplier_create"),
    path("furnizori/<int:pk>/", views.SupplierDetailView.as_view(), name="supplier_detail"),
    path("furnizori/<int:pk>/editare/", views.SupplierUpdateView.as_view(), name="supplier_update"),
    path("produse/", views.ProductListView.as_view(), name="product_list"),
    path("produse/nou/", views.ProductCreateView.as_view(), name="product_create"),
    path("produse/<int:pk>/", views.ProductDetailView.as_view(), name="product_detail"),
    path("produse/<int:pk>/editare/", views.ProductUpdateView.as_view(), name="product_update"),
]
