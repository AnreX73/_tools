"""URL-маршруты приложения orders."""
from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("order/<uuid:uuid>/", views.detail, name="detail"),
]
