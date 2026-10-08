"""
shop/catalog.py

Логика публичного каталога: разбор фильтров из query-параметров, выборка
товаров и построение боковых фасетов (значения + количество).

Параметры в URL:

    a__<code>           = значение (можно несколько раз: ИЛИ внутри характеристики)
    a__<code>__min      = нижняя граница для числовых характеристик
    a__<code>__max      = верхняя граница
    sort                = name | price | -price | -created_at
    page                = страница

Значения лежат в Product.attributes (JSONB), поэтому фильтры используют
jsonb @> (GIN-индекс product_attrs_gin) и диапазоны по ключу.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlencode

from django.db.models import F, FloatField, Max, Min, Q
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast

from .models import Attribute, Category

VALUE_PREFIX = "a__"
MIN_SUFFIX = "__min"
MAX_SUFFIX = "__max"

SORT_CHOICES = [
    ("default", "По умолчанию"),      # <- новый пункт, порядок из админки
    ("name", "По названию"),
    ("price", "Сначала дешёвые"),
    ("-price", "Сначала дорогие"),
    ("-created_at", "Сначала новые"),
]
DEFAULT_SORT = "default"              # было "name"
_SORT_KEYS = {key for key, _ in SORT_CHOICES}

T = Attribute.DataType


# --------------------------------------------------------------------------
# Разбор и представление состояния фильтров
# --------------------------------------------------------------------------
@dataclass
class FilterState:
    values: dict[str, list[str]] = field(default_factory=dict)
    ranges: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)
    sort: str = DEFAULT_SORT

    # -- сериализация обратно в query-параметры --
    def pairs(self) -> list[tuple[str, object]]:
        out: list[tuple[str, object]] = []
        for code, values in self.values.items():
            for value in values:
                out.append((f"{VALUE_PREFIX}{code}", value))
        for code, (low, high) in self.ranges.items():
            if low is not None:
                out.append((f"{VALUE_PREFIX}{code}{MIN_SUFFIX}", low))
            if high is not None:
                out.append((f"{VALUE_PREFIX}{code}{MAX_SUFFIX}", high))
        if self.sort != DEFAULT_SORT:
            out.append(("sort", self.sort))
        return out

    def querystring(self) -> str:
        return urlencode(self.pairs())

    def has_active(self) -> bool:
        return bool(self.values or self.ranges)


def _as_number(raw):
    if raw is None:
        return None
    try:
        return float(str(raw).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _as_int(value):
    return int(value) if float(value).is_integer() else value


def parse_filters(get_params, schema) -> FilterState:
    """Превращает request.GET в FilterState, отбрасывая всё, чего нет в схеме."""
    state = FilterState(sort=_valid_sort(get_params.get("sort")))
    for code, link in schema.items():
        if not link.is_filterable:
            continue
        attr = link.attribute

        if attr.has_options:
            allowed = {o.code for o in attr.options.all()}
            selected = [v for v in get_params.getlist(f"{VALUE_PREFIX}{code}") if v in allowed]
            if selected:
                state.values[code] = list(dict.fromkeys(selected))  # без дублей, порядок сохраняем
        elif attr.data_type == T.BOOLEAN:
            selected = [v for v in get_params.getlist(f"{VALUE_PREFIX}{code}") if v in ("true", "false")]
            if selected:
                state.values[code] = list(dict.fromkeys(selected))
        elif attr.data_type in (T.INTEGER, T.DECIMAL):
            low = _as_number(get_params.get(f"{VALUE_PREFIX}{code}{MIN_SUFFIX}"))
            high = _as_number(get_params.get(f"{VALUE_PREFIX}{code}{MAX_SUFFIX}"))
            if low is not None or high is not None:
                state.ranges[code] = (low, high)
    return state


def _valid_sort(raw) -> str:
    return raw if raw in _SORT_KEYS else DEFAULT_SORT


# --------------------------------------------------------------------------
# Выборка товаров
# --------------------------------------------------------------------------
def apply_filters(qs, values, ranges, schema=None):
    """
    ИЛИ внутри одной характеристики, И между разными.
    Схема нужна, чтобы отличить мультивыбор: для MULTI в JSONB лежит список,
    и @> должен получать список («work_materials»: ["steel"]), а не строку.
    """
    schema = schema or {}
    for code, selected in values.items():
        link = schema.get(code)
        is_multi = link is not None and link.attribute.data_type == T.MULTI
        condition = Q()
        for value in selected:
            if value == "true":
                payload = True
            elif value == "false":
                payload = False
            else:
                payload = [value] if is_multi else value
            condition |= Q(attributes__contains={code: payload})
        qs = qs.filter(condition)
    for code, (low, high) in ranges.items():
        if low is not None:
            qs = qs.filter(**{f"attributes__{code}__gte": low})
        if high is not None:
            qs = qs.filter(**{f"attributes__{code}__lte": high})
    return qs


def apply_sort(qs, sort):
    if sort == "price":
        return qs.order_by(F("price").asc(nulls_last=True), "name", "pk")
    if sort == "-price":
        return qs.order_by(F("price").desc(nulls_last=True), "name", "pk")
    if sort == "-created_at":
        return qs.order_by("-created_at", "name", "pk")
    return qs.order_by("name", "pk")


# --------------------------------------------------------------------------
# Фасеты: значения и количество по каждому фильтру
# --------------------------------------------------------------------------
def option_counts(qs, attr) -> Counter:
    """
    Считает, сколько товаров в выборке имеют каждое значение характеристики.
    Один запрос на характеристику: забираем только нужный ключ JSONB.
    """
    raw = (qs.filter(attributes__has_key=attr.code)
             .values_list(f"attributes__{attr.code}", flat=True))
    counts: Counter = Counter()
    for value in raw:
        if isinstance(value, list):
            counts.update(value)
        elif isinstance(value, bool):
            counts["true" if value else "false"] += 1
        elif value is not None:
            counts[value] += 1
    return counts


def range_bounds(qs, attr):
    """(min, max) значения характеристики среди товаров выборки."""
    expression = Cast(KeyTextTransform(attr.code, "attributes"), FloatField())
    result = qs.annotate(_value=expression).aggregate(low=Min("_value"), high=Max("_value"))
    low, high = result["low"], result["high"]
    return (_as_int(low) if low is not None else None,
            _as_int(high) if high is not None else None)


def _option(code, label, count, selected) -> dict:
    """Значение фасета + признак «нет товаров с этим значением»."""
    return {
        "code": code,
        "label": label,
        "count": count,
        "selected": selected,
        "disabled": count == 0 and not selected,
    }


def build_facets(scope_qs, schema, state: FilterState) -> list[dict]:
    """
    Для каждой фильтруемой характеристики отдаёт значения/границы и количество.
    Считает по выборке БЕЗ фильтра самой этой характеристики — иначе выбранные
    значения «съедали» бы свои же счётчики.
    """
    facets: list[dict] = []
    for code, link in schema.items():
        if not link.is_filterable:
            continue
        attr = link.attribute
        others_values = {k: v for k, v in state.values.items() if k != code}
        others_ranges = {k: v for k, v in state.ranges.items() if k != code}
        qs = apply_filters(scope_qs, others_values, others_ranges, schema)
        selected = state.values.get(code, [])

        if attr.has_options:
            counts = option_counts(qs, attr)
            options = [
                _option(o.code, o.label, counts.get(o.code, 0), o.code in selected)
                for o in attr.options.all()
            ]
            facets.append({
                "code": code, "attr": attr, "kind": "options",
                "options": options, "selected": selected,
            })
        elif attr.data_type == T.BOOLEAN:
            counts = option_counts(qs, attr)
            options = [
                _option("true", "Да", counts.get("true", 0), "true" in selected),
                _option("false", "Нет", counts.get("false", 0), "false" in selected),
            ]
            facets.append({
                "code": code, "attr": attr, "kind": "options",
                "options": options, "selected": selected,
            })
        elif attr.data_type in (T.INTEGER, T.DECIMAL):
            low, high = range_bounds(qs, attr)
            selected_low, selected_high = state.ranges.get(code, (None, None))
            facets.append({
                "code": code, "attr": attr, "kind": "range",
                "min": low, "max": high,
                "sel_min": selected_low, "sel_max": selected_high,
                "selected": state.ranges.get(code),
            })
    return facets


def build_chips(schema, state: FilterState) -> list[dict]:
    """Плашки активных фильтров. У каждой — query-параметры без этого фильтра."""
    chips: list[dict] = []
    for code, selected in state.values.items():
        link = schema.get(code)
        if not link:
            continue
        attr = link.attribute
        labels = {o.code: o.label for o in attr.options.all()}
        for value in selected:
            pairs = [(k, v) for k, v in state.pairs()
                     if not (k == f"{VALUE_PREFIX}{code}" and v == value)]
            label = labels.get(value, "Да" if value == "true" else "Нет")
            chips.append({"label": f"{attr.name}: {label}", "query": urlencode(pairs)})
    for code, (low, high) in state.ranges.items():
        link = schema.get(code)
        if not link:
            continue
        attr = link.attribute
        if low is not None and high is not None:
            text = f"{_short(low)}–{_short(high)}"
        elif low is not None:
            text = f"от {_short(low)}"
        else:
            text = f"до {_short(high)}"
        drop = {f"{VALUE_PREFIX}{code}{MIN_SUFFIX}", f"{VALUE_PREFIX}{code}{MAX_SUFFIX}"}
        pairs = [(k, v) for k, v in state.pairs() if k not in drop]
        unit = f" {attr.unit}" if attr.unit else ""
        chips.append({"label": f"{attr.name}: {text}{unit}", "query": urlencode(pairs)})
    return chips


def _short(value):
    return int(value) if float(value).is_integer() else value


# --------------------------------------------------------------------------
# Отображение характеристик товара
# --------------------------------------------------------------------------
def attribute_display_maps():
    """{code: Attribute} и {code: {option_code: label}} — два запроса на весь каталог."""
    attrs = {a.code: a for a in Attribute.objects.filter(is_active=True)}
    labels = {
        a.code: {o.code: o.label for o in a.options.all()}
        for a in Attribute.objects.filter(is_active=True).prefetch_related("options")
    }
    return attrs, labels


def format_attribute_value(attr, labels, value, with_unit=True) -> str:
    if value in (None, "", []):
        return ""
    if attr.data_type == T.BOOLEAN:
        text = "Да" if value else "Нет"
    elif attr.data_type == T.CHOICE:
        text = labels.get(attr.code, {}).get(value, str(value))
    elif attr.data_type == T.MULTI:
        text = ", ".join(labels.get(attr.code, {}).get(v, str(v)) for v in value)
    else:
        text = str(_short(value)) if isinstance(value, float) else str(value)
    return f"{text} {attr.unit}".strip() if (attr.unit and with_unit) else text


def category_breadcrumb_map(categories) -> dict[int, list[str]]:
    """
    {category.pk: [имя корня, ..., имя этой категории]} для набора категорий
    (например категорий товаров в выдаче поиска), одним доп запросом на всех
    предков сразу, без N+1.
    """
    categories = list(categories)
    if not categories:
        return {}
    steplen = Category.steplen
    prefixes = set()
    for cat in categories:
        prefixes.update(cat.path[:i] for i in range(steplen, len(cat.path), steplen))
    names_by_path = {cat.path: cat.name for cat in categories}
    if prefixes:
        names_by_path.update(
            Category.objects.filter(path__in=prefixes).values_list("path", "name")
        )
    result = {}
    for cat in categories:
        own_prefixes = [cat.path[:i] for i in range(steplen, len(cat.path) + steplen, steplen)]
        result[cat.pk] = [names_by_path[p] for p in own_prefixes if p in names_by_path]
    return result


def product_specs(product, attrs, labels, codes=None, limit=None) -> list[dict]:
    """Короткий список характеристик товара для карточки/страницы товара."""
    codes = codes if codes is not None else list(product.attributes.keys())
    specs = []
    for code in codes:
        attr = attrs.get(code)
        value = product.attributes.get(code)
        if attr is None or value in (None, "", []):
            continue
        specs.append({
            "code": code,
            "label": attr.name,
            "value": format_attribute_value(attr, labels, value),
        })
        if limit and len(specs) >= limit:
            break
    return specs


def short_spec(product, attrs, labels, codes, sep="*") -> dict:
    """
    Компактная строка для кнопки товара в списке: «10×72 · TiAlN».

    codes — коды характеристик в порядке приоритета (из правил сортировки);
    значения выводятся СТРОГО в этом порядке. Числовые характеристики, идущие
    подряд, склеиваются через «×», всё остальное разделяется « · »:
        диаметр, длина, покрытие  ->  10×72 · TiAlN
        покрытие, диаметр, длина  ->  TiAlN · 10×72
        диаметр, покрытие, длина  ->  10 · TiAlN · 72
    Единицы и подписи не выводятся: их объясняет "hint" — текст для всплывающей
    подсказки («Диаметр, мм × Длина, мм · Покрытие»).
    Если у товара нет числа в середине цепочки, ставится «–», чтобы позиции не
    «съезжали»; пустой хвост цепочки отбрасывается. Нечисловое значение, которого
    нет, пропускается. Логические и множественные характеристики не выводятся.
    """
    runs = []   # [is_numeric, [значения], [названия]]
    for code in codes:
        attr = attrs.get(code)
        if attr is None or attr.data_type in (T.BOOLEAN, T.MULTI):
            continue
        value = product.attributes.get(code)
        text = "" if value in (None, "", []) else format_attribute_value(
            attr, labels, value, with_unit=False)
        name = f"{attr.name}, {attr.unit}" if attr.unit else attr.name
        numeric = attr.data_type in (T.INTEGER, T.DECIMAL)

        if not numeric and not text:
            continue
        if numeric and runs and runs[-1][0]:          # продолжаем цепочку чисел
            runs[-1][1].append(text or "–")
            runs[-1][2].append(name)
        else:
            runs.append([numeric, [text or "–"], [name]])

    parts, names = [], []
    for numeric, texts, run_names in runs:
        if numeric:
            while texts and texts[-1] == "–":         # хвост без значений не показываем
                texts.pop()
                run_names.pop()
            if not texts:
                continue
            parts.append(sep.join(texts))
            names.append(f" {sep} ".join(run_names))
        else:
            parts.append(texts[0])
            names.append(run_names[0])
    return {"text": " · ".join(parts), "hint": " · ".join(names)}