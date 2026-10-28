from django.urls import path

from . import views

app_name = "shop"

urlpatterns = [
    path("", views.index, name="index"),
    path("catalog/", views.catalog_index, name="catalog"),
    path("catalogs/", views.catalogs_list, name="catalogs"),
    path("catalog/<slug:slug>/", views.category_detail, name="category"),
    path("product/<slug:slug>/", views.product_detail, name="product"),
    path("product/<slug:slug>/card/", views.product_card, name="product_card"),
    path("search/", views.search_results, name="search"),
    path("search/suggest/", views.search_suggest, name="search_suggest"),
    # Старые адреса юридических документов редиректят на табы /legal/.
    path("offer/", views.info_page, {"slug": "offer"}, name="offer"),
    path("privacy/", views.info_page, {"slug": "privacy"}, name="privacy"),
    path("legal/", views.legal_info, name="legal"),
    path("info/<slug:slug>/", views.info_page, name="info"),
    # Десктоп: каскадная навигация по каталогу (колонки + аккордеон слева).
    # Мобильная версия эти эндпоинты не использует.
    path("cascade/", views.cascade_root, name="cascade_root"),
    path("cascade/<slug:slug>/", views.cascade_level, name="cascade_level"),
]
