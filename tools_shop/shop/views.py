from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from . import catalog, search
from .models import Category, Product

PAGE_SIZE = 24
SUGGEST_PRODUCTS = 6
SUGGEST_CATEGORIES = 4


def _root_categories():
    return Category.objects.filter(depth=1, is_active=True).order_by("path")


def index(request):
    context = {
        "title": "Главная страница",
        "root_categories": _root_categories(),
    }
    return render(request, "shop/index.html", context)


def catalog_index(request):
    context = {
        "title": "Каталог",
        "root_categories": _root_categories(),
    }
    return render(request, "shop/catalog_index.html", context)


def _category_products(category, schema, state, request):
    """Товары листовой категории + их характеристики для отображения в списке."""
    scope = category.product_scope()
    products_qs = catalog.apply_sort(
        catalog.apply_filters(scope, state.values, state.ranges, schema), state.sort
    )
    page = Paginator(products_qs, PAGE_SIZE).get_page(request.GET.get("page"))

    attrs, labels = catalog.attribute_display_maps()
    spec_codes = list(schema) if category.numchild == 0 else None
    products = [
        {"product": product,
         "specs": catalog.product_specs(product, attrs, labels, spec_codes, limit=4)}
        for product in page
    ]
    return scope, page, products


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug, is_active=True)
    schema = category.get_attribute_schema()
    state = catalog.parse_filters(request.GET, schema)

    scope, page, products = _category_products(category, schema, state, request)

    context = {
        "title": category.name,
        "category": category,
        "ancestors": category.path_ancestors(),
        "children": category.children_list(),
        "facets": catalog.build_facets(scope, schema, state),
        "chips": catalog.build_chips(schema, state),
        "state": state,
        "sort_options": [
            {"value": value, "label": label,
             "attrs": " selected" if value == state.sort else ""}
            for value, label in catalog.SORT_CHOICES
        ],
        "base_query": state.querystring(),
        "page": page,
        "products": products,
        "total": page.paginator.count,
    }

    if request.headers.get("HX-Request"):
        return render(request, "shop/partials/catalog_body.html", context)

    # Полная загрузка страницы: мобильный шаблон не меняется (category.html,
    # блок cascade скрыт на десктопе CSS-breakpoint'ом). Десктопу передаётся путь
    # slug от корня до текущей категории — JS раскрывает каскад теми же запросами
    # к shop:cascade_level, что и при кликах, без дублирования разметки.
    context["root_categories"] = _root_categories()
    context["cascade_path"] = [c.slug for c in category.path_ancestors()] + [category.slug]
    return render(request, "shop/category.html", context)


def cascade_root(request):
    """Десктоп: левая колонка (htmx-фрагмент, используется при возврате к началу каскада)."""
    context = {"root_categories": _root_categories(), "active": None}
    return render(request, "shop/partials/cascade_root.html", context)


def cascade_level(request, slug):
    """
    Десктоп: один уровень каскада — колонка справа. Если категория не лист —
    её дети (кнопки для следующей колонки). Если лист — список товаров тем же
    компонентом, что и результаты поиска.
    """
    category = get_object_or_404(Category, slug=slug, is_active=True)
    context = {"category": category, "depth": category.depth}

    if category.numchild == 0:
        schema = category.get_attribute_schema()
        state = catalog.parse_filters(request.GET, schema)
        scope, page, products = _category_products(category, schema, state, request)
        context.update({
            "is_leaf": True,
            "page": page,
            "products": products,
            "total": page.paginator.count,
            "base_query": state.querystring(),
        })
    else:
        context.update({"is_leaf": False, "children": category.children_list()})

    return render(request, "shop/partials/cascade_level.html", context)


def product_card(request, slug):
    """
    Десктоп: фрагмент карточки товара, раскрываемый на месте в списке (строка-
    дропдаун), без перехода на отдельную страницу. Используется и в каскаде
    каталога, и в результатах поиска — один и тот же компонент.
    """
    product = get_object_or_404(
        Product.objects.select_related("category", "brand"), slug=slug, is_active=True
    )
    attrs, labels = catalog.attribute_display_maps()
    schema = product.category.get_attribute_schema()
    context = {
        "product": product,
        "specs": catalog.product_specs(product, attrs, labels, list(schema)),
    }
    return render(request, "shop/partials/product_card_inline.html", context)


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("category", "brand"), slug=slug, is_active=True
    )
    attrs, labels = catalog.attribute_display_maps()
    schema = product.category.get_attribute_schema()
    context = {
        "title": product.name,
        "product": product,
        "ancestors": product.category.path_ancestors(),
        "specs": catalog.product_specs(product, attrs, labels, list(schema)),
        "siblings": (Product.objects.active()
                     .filter(category=product.category)
                     .exclude(pk=product.pk)
                     .order_by("name")[:6]),
    }
    return render(request, "shop/product_detail.html", context)


def search_suggest(request):
    """Выпадающие подсказки под строкой поиска (htmx-фрагмент)."""
    query = search.clean_query(request.GET.get("q"))
    context = {"query": query, "searchable": search.is_searchable(query)}
    if context["searchable"]:
        products_qs = search.search_products(query)
        context.update({
            "categories": search.search_categories(query, SUGGEST_CATEGORIES),
            "products": list(products_qs[:SUGGEST_PRODUCTS]),
            "total": products_qs.count(),
        })
    return render(request, "shop/partials/search_suggest.html", context)


def search_results(request):
    """Полная страница результатов поиска."""
    query = search.clean_query(request.GET.get("q"))
    searchable = search.is_searchable(query)
    products_qs = search.search_products(query)
    page = Paginator(products_qs, PAGE_SIZE).get_page(request.GET.get("page"))
    products = list(page)
    breadcrumbs = catalog.category_breadcrumb_map(p.category for p in products)
    context = {
        "title": f"Поиск: {query}" if query else "Поиск",
        "query": query,
        "searchable": searchable,
        "min_length": search.MIN_QUERY_LENGTH,
        "categories": search.search_categories(query, 8) if searchable else [],
        "page": page,
        "products": [
            {"product": product, "specs": [],
             "breadcrumb": breadcrumbs.get(product.category_id, [])}
            for product in products
        ],
        "total": page.paginator.count,
    }
    return render(request, "shop/search.html", context)
