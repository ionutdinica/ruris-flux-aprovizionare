"""Autentificare: folosim view-urile gata făcute și testate din Django,
cu șabloanele noastre (în templates/registration/)."""

from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

app_name = "accounts"

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "parola/",
        auth_views.PasswordChangeView.as_view(
            success_url=reverse_lazy("accounts:password_change_done")
        ),
        name="password_change",
    ),
    path(
        "parola/schimbata/",
        auth_views.PasswordChangeDoneView.as_view(),
        name="password_change_done",
    ),
]
