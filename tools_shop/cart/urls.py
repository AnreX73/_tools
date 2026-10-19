"""URL-маршруты приложения cart."""
from django.urls import path

from . import views

app_name = "cart"

urlpatterns = [
    path("", views.detail, name="detail"),
    path("favorites/", views.favorites_detail, name="favorites"),
    path("badge/", views.badge, name="badge"),
    path("favorites/badge/", views.favorites_badge, name="favorites_badge"),
    path("state/", views.state, name="state"),
    path("add/<int:product_id>/", views.add, name="add"),
    path("update/<int:product_id>/", views.update, name="update"),
    path("remove/<int:product_id>/", views.remove, name="remove"),
    path("clear/", views.clear, name="clear"),
    path("favorites/toggle/<int:product_id>/", views.favorite_toggle, name="favorite_toggle"),
    path("favorites/add/<int:product_id>/", views.favorite_add, name="favorite_add"),
    path("favorites/remove/<int:product_id>/", views.favorite_remove, name="favorite_remove"),
]
