from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("", views.ActivityLogView.as_view(), name="log"),
]
