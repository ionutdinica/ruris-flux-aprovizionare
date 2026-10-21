from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.NotificationListView.as_view(), name="log"),
    path("<int:pk>/", views.NotificationDetailView.as_view(), name="detail"),
    path("trimite-acum/", views.SendNowView.as_view(), name="send_now"),
]
