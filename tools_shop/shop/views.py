from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from . import catalog, search
from .models import Category, Product

PAGE_SIZE = 24
SUGGEST_PRODUCTS = 6
SUGGEST_CATEGORIES = 4


def index(request):
    context = {
        "title": "Главная страница",
        "root_categories": Category.objects.filter(depth=1, is_active=True).order_by("path"),
    }
    return render(request, "shop/index.html", context)


def catalog_index(request):
    context = {
        "title": "Каталог",
        "root_categories": Category.objects.filter(depth=1, is_active=True).order_by("path"),
    }
    return render(request, "shop/catalog_index.html", context)


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug, is_active=True)
    schema = category.get_attribute_schema()
    state = catalog.parse_filters(request.GET, schema)

    scope = category.product_scope()
    products_qs = catalog.apply_sort(
        catalog.apply_filters(scope, state.values, state.ranges, schema), state.sort
    )
    page = Paginator(products_qs, PAGE_SIZE).get_page(request.GET.get("page"))

    attrs, labels = catalog.attribute_display_maps()
    # В конечной категории характеристики показываем в порядке схемы.
    spec_codes = list(schema) if category.numchild == 0 else None
    products = [
        {"product": product,
         "specs": catalog.product_specs(product, attrs, labels, spec_codes, limit=4)}
        for product in page
    ]

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
    template = ("shop/partials/catalog_body.html"
                if request.headers.get("HX-Request") else "shop/category.html")
    return render(request, template, context)


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
    context = {
        "title": f"Поиск: {query}" if query else "Поиск",
        "query": query,
        "searchable": searchable,
        "min_length": search.MIN_QUERY_LENGTH,
        "categories": search.search_categories(query, 8) if searchable else [],
        "page": page,
        "products": [{"product": product, "specs": []} for product in page],
        "total": page.paginator.count,
    }
    return render(request, "shop/search.html", context)
