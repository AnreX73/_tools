"""
shop/search.py

Поиск по каталогу для строки поиска в шапке (подсказки) и страницы /search/.

Правила:
  * запрос режется на слова; товар подходит, если КАЖДОЕ слово встречается
    в названии, артикуле или бренде (без учёта регистра, «ё» = «е»,
    десятичная запятая = точка: «0,20» находит «Ø0.20»);
  * артикул дополнительно сравнивается «в сжатом виде» — без пробелов,
    дефисов, точек и т.п., поэтому «dr001» находит «DR-001»;
  * выдача ранжируется: точный артикул → артикул с начала → название
    с начала → остальное, затем по названию.

Для каталога на тысячи позиций хватает ILIKE; если товаров станет сотни
тысяч — переводить на pg_trgm / полнотекстовый индекс.
"""
from __future__ import annotations

import re

from django.db.models import Case, F, Func, IntegerField, Q, Value, When
from django.db.models.functions import Coalesce, Concat, Lower, Replace

from .models import Category, Product

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 100
MAX_TOKENS = 8

_SPLIT_RE = re.compile(r"\s+")
_COMPACT_RE = re.compile(r"[^0-9a-zа-я]+")


def normalize(text: str) -> str:
    return (text or "").lower().replace("ё", "е").replace(",", ".").strip()


def compact(text: str) -> str:
    """Строка без разделителей: «DR-001 / 6.0» → «dr00160»."""
    return _COMPACT_RE.sub("", normalize(text))


def clean_query(raw) -> str:
    """Обрезанный запрос с одиночными пробелами (то, что показываем пользователю)."""
    return _SPLIT_RE.sub(" ", (raw or "").strip())[:MAX_QUERY_LENGTH]


def tokens(query: str) -> list[str]:
    seen, result = set(), []
    for token in _SPLIT_RE.split(normalize(query)):
        if token and token not in seen:
            seen.add(token)
            result.append(token)
    return result[:MAX_TOKENS]


def is_searchable(query: str) -> bool:
    return len(normalize(query)) >= MIN_QUERY_LENGTH


# --------------------------------------------------------------------------
# SQL-выражения
# --------------------------------------------------------------------------
def _norm(expr):
    """lower(x), ё→е, «,»→«.» — то же, что normalize() на стороне Python."""
    return Replace(Replace(Lower(expr), Value("ё"), Value("е")), Value(","), Value("."))


class _RegexpReplace(Func):
    function = "regexp_replace"
    arity = 4


def _compact_sql(expr):
    return _RegexpReplace(_norm(expr), Value("[^0-9a-zа-я]+"), Value(""), Value("g"))


def search_products(query: str):
    """QuerySet активных товаров, подходящих под запрос, уже отсортированный."""
    words = tokens(query)
    if not words or not is_searchable(query):
        return Product.objects.none()

    qs = (Product.objects.active()
          .select_related("category", "brand")
          .annotate(
              _haystack=_norm(Concat(
                  "name", Value(" "), "sku", Value(" "), Coalesce("brand__name", Value("")),
              )),
              _sku_norm=_norm("sku"),
              _sku_compact=_compact_sql("sku"),
              _name_norm=_norm("name"),
          ))

    for word in words:
        condition = Q(_haystack__contains=word)
        word_compact = compact(word)
        if word_compact:
            condition |= Q(_sku_compact__contains=word_compact)
        qs = qs.filter(condition)

    full = normalize(query)
    full_compact = compact(query)
    qs = qs.annotate(_rank=Case(
        When(Q(_sku_norm=full) | Q(_sku_compact=full_compact), then=Value(0)),
        When(_sku_compact__startswith=full_compact or full, then=Value(1)),
        When(_name_norm__startswith=full, then=Value(2)),
        When(_name_norm__contains=full, then=Value(3)),
        default=Value(4),
        output_field=IntegerField(),
    ))
    return qs.order_by("_rank", "name", "pk")


def search_categories(query: str, limit: int = 4):
    """Активные категории, в названии которых есть все слова запроса."""
    words = tokens(query)
    if not words or not is_searchable(query):
        return []
    qs = Category.objects.filter(is_active=True).annotate(_name_norm=_norm("name"))
    for word in words:
        qs = qs.filter(_name_norm__contains=word)
    qs = qs.annotate(_rank=Case(
        When(_name_norm__startswith=normalize(query), then=Value(0)),
        default=Value(1),
        output_field=IntegerField(),
    )).order_by("_rank", F("depth").asc(), "name")
    return list(qs[:limit])
