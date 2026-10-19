"""URL-маршруты приложения checkout."""
from django.urls import path

from . import views

app_name = "checkout"

urlpatterns = [
    path("", views.index, name="index"),
    path("suggest-by-inn/", views.suggest_by_inn, name="suggest_by_inn"),
]
