from django.urls import path

from . import views

app_name = "currency"

urlpatterns = [
    path("", views.RateListView.as_view(), name="rate_list"),
    path("curs-aplicabil/", views.RateLookupView.as_view(), name="rate_lookup"),
    path("actualizeaza/", views.RateRefreshView.as_view(), name="rate_refresh"),
]
