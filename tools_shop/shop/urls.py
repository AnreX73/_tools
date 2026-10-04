from django.urls import path

from . import views

app_name = "shop"

urlpatterns = [
    path("", views.index, name="index"),
    path("catalog/", views.catalog_index, name="catalog"),
    path("catalog/<slug:slug>/", views.category_detail, name="category"),
    path("product/<slug:slug>/", views.product_detail, name="product"),
    path("search/", views.search_results, name="search"),
    path("search/suggest/", views.search_suggest, name="search_suggest"),
]
