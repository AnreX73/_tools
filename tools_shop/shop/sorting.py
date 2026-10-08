"""
shop/sorting.py — новый файл.

Использование во view:

    from .sorting import order_products
    qs = category.product_scope()             # + ваши фильтры htmx
    qs = order_products(qs, category)         # порядок, заданный в админке
"""
from django.db.models import F, FloatField
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Lower

from .models import Attribute, CategorySortRule

PREFIX = CategorySortRule.ATTR_PREFIX

# Встроенные поля -> выражение для ORDER BY
BUILTIN_EXPRESSIONS = {
    "name": lambda: Lower("name"),
    "sku": lambda: F("sku"),
    "price": lambda: F("price"),
    "brand": lambda: F("brand__name"),
    "created_at": lambda: F("created_at"),
}


def sort_field_choices():
    """Choices для выпадающего списка в админке (с группами)."""
    attrs = (Attribute.objects.filter(is_active=True)
             .exclude(data_type=Attribute.DataType.MULTI)  # список значений не сортируется осмысленно
             .order_by("name"))
    return [
        ("", "---------"),
        ("Основные поля", list(CategorySortRule.BUILTIN_LABELS.items())),
        ("Характеристики", [(f"{PREFIX}{a.code}", str(a)) for a in attrs]),
    ]


def get_sort_rules(category):
    """
    Правила берутся у ближайшей категории вверх по дереву (включая саму),
    у которой они заданы. Так можно задать порядок один раз на «Металлорежущий
    инструмент», а для «Фрезы концевой» переопределить.
    """
    ids = [*category.ancestor_ids(), category.pk]
    rules = (CategorySortRule.objects
             .filter(category_id__in=ids)
             .order_by("-category__depth", "sort_order"))
    result, owner_id = [], None
    for rule in rules:
        if owner_id is None:
            owner_id = rule.category_id
        if rule.category_id != owner_id:
            break
        result.append(rule)
    return result


def build_ordering(rules):
    codes = [r.field[len(PREFIX):] for r in rules if r.field.startswith(PREFIX)]
    attrs = {a.code: a for a in Attribute.objects.filter(code__in=codes, is_active=True)}
    numeric = (Attribute.DataType.INTEGER, Attribute.DataType.DECIMAL)

    ordering, seen = [], set()
    for rule in rules:
        if rule.field in seen:
            continue
        seen.add(rule.field)

        if rule.field in BUILTIN_EXPRESSIONS:
            expr = BUILTIN_EXPRESSIONS[rule.field]()
        elif rule.field.startswith(PREFIX):
            attr = attrs.get(rule.field[len(PREFIX):])
            if attr is None or attr.data_type == Attribute.DataType.MULTI:
                continue  # характеристику удалили/отключили — пропускаем правило
            expr = KeyTextTransform(attr.code, "attributes")
            if attr.data_type in numeric:
                # без Cast диаметры сортировались бы как строки: "10" < "6"
                expr = Cast(expr, FloatField())
        else:
            continue

        # товары без значения всегда в конце, в какую бы сторону ни сортировали
        ordering.append(expr.desc(nulls_last=True) if rule.descending
                        else expr.asc(nulls_last=True))

    ordering.append("pk")  # стабильный порядок => пагинация не «прыгает»
    return ordering


def sort_attribute_codes(rules):
    """
    Коды характеристик из правил сортировки: в порядке приоритета, без повторов.
    Встроенные поля (название, цена...) пропускаются — они и так видны в строке товара.
    """
    codes = [r.field[len(PREFIX):] for r in rules if r.field.startswith(PREFIX)]
    return list(dict.fromkeys(codes))


def order_products(queryset, category, rules=None):
    # rules можно передать готовые, чтобы не ходить в БД за ними второй раз
    rules = get_sort_rules(category) if rules is None else rules
    if not rules:
        return queryset.order_by("name", "pk")  # поведение по умолчанию
    return queryset.order_by(*build_ordering(rules))
