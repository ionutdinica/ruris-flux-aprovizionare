from django.urls import path

from . import views

app_name = "budgets"

urlpatterns = [
    path("", views.BudgetListView.as_view(), name="budget_list"),
    path("nou/", views.BudgetCreateView.as_view(), name="budget_create"),
    path("<int:pk>/editare/", views.BudgetUpdateView.as_view(), name="budget_update"),
]
