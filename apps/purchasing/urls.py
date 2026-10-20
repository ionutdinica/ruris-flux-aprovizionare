from django.urls import path

from . import views

app_name = "purchasing"

urlpatterns = [
    path("", views.OrderListView.as_view(), name="order_list"),
    path("noua/", views.OrderCreateView.as_view(), name="order_create"),
    path("<int:pk>/", views.OrderDetailView.as_view(), name="order_detail"),
    path("<int:pk>/editare/", views.OrderUpdateView.as_view(), name="order_update"),
    path("<int:pk>/trimite/", views.OrderSendView.as_view(), name="order_send"),
    path("<int:pk>/anuleaza/", views.OrderCancelView.as_view(), name="order_cancel"),
    path("<int:pk>/inchide/", views.OrderCloseView.as_view(), name="order_close"),
]
