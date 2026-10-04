"""
shop/models.py

Концепция:
  * Category          — дерево (django-treebeard), товары лежат только в листьях.
  * Attribute         — справочник характеристик (клиент создаёт сам в админке).
  * AttributeOption   — варианты для характеристик типа «выбор».
  * CategoryAttribute — какие характеристики относятся к категории (наследуются вниз).
  * Product           — один артикул (SKU); значения характеристик в JSONB `attributes`,
                        ключ = Attribute.code.

Предполагается, что в shop/utils.py есть make_slug(text: str) -> str
(латиница, нижний регистр, слова через дефис).
"""
import re
import unicodedata
import uuid

from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, transaction
from treebeard.mp_tree import MP_Node

from .utils import make_slug


# --------------------------------------------------------------------------
# Общие хелперы
# --------------------------------------------------------------------------
class SlugWithIdMixin(models.Model):
    """
    slug = make_slug(<slug_source_field>) + "-" + pk, например «frezy-kontsevye-17».
    pk известен только после INSERT, поэтому при создании сначала пишем временный
    уникальный slug, затем сразу обновляем (всё в одной транзакции).
    Slug не меняется при переименовании — чтобы не ломались ссылки.
    """
    slug = models.SlugField("Slug", max_length=255, unique=True, blank=True, editable=False)
    slug_source_field = "name"

    class Meta:
        abstract = True

    def build_slug(self):
        base = make_slug(getattr(self, self.slug_source_field) or "")
        # make_slug знает только кириллицу, а в названиях встречаются символы
        # вроде «Ø» (диаметр). URL-конвертер <slug:...> принимает только ASCII,
        # поэтому всё нелатинское из slug выкидываем.
        base = (unicodedata.normalize("NFKD", base)
                .encode("ascii", "ignore").decode("ascii"))
        base = re.sub(r"-+", "-", base)[:200].strip("-")
        return f"{base}-{self.pk}" if base else str(self.pk)

    def save(self, *args, **kwargs):
        if self.slug:
            return super().save(*args, **kwargs)
        with transaction.atomic():
            self.slug = uuid.uuid4().hex  # временный
            super().save(*args, **kwargs)
            self.slug = self.build_slug()
            type(self)._default_manager.filter(pk=self.pk).update(slug=self.slug)


def make_code(text, prefix):
    """Латинский код для JSON-ключа: «Диаметр» -> diametr; «40Х» -> o_40kh."""
    code = re.sub(r"[^a-z0-9]+", "_", make_slug(text)).strip("_")
    if not code or not code[0].isalpha():
        code = f"{prefix}_{code}".strip("_")
    return code[:60]


# --------------------------------------------------------------------------
# Дерево категорий
# --------------------------------------------------------------------------
class Category(SlugWithIdMixin, MP_Node):
    name = models.CharField("Название", max_length=255)
    description = models.TextField("Описание", blank=True)
    is_active = models.BooleanField("Показывать на сайте", default=True)

    # node_order_by НЕ задаём: порядок узлов клиент меняет перетаскиванием
    # в админке (treebeard.admin.TreeAdmin).

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("shop:category", args=[self.slug])

    # ---- обход дерева напрямую по path ------------------------------------
    # В treebeard 7 методы get_ancestors()/get_children() объявлены устаревшими
    # (удаление в 8-й версии), поэтому ходим по materialized path сами: формат
    # path — это склейка сегментов фиксированной длины steplen.
    def ancestor_ids(self):
        """pk всех предков, от корня к родителю."""
        if self.depth <= 1:
            return []
        prefixes = [self.path[:i] for i in range(self.steplen, len(self.path), self.steplen)]
        return list(type(self).objects.filter(path__in=prefixes).values_list("pk", flat=True))

    def path_ancestors(self):
        """Предки категории, упорядоченные от корня к родителю (для хлебных крошек)."""
        if self.depth <= 1:
            return type(self).objects.none()
        prefixes = [self.path[:i] for i in range(self.steplen, len(self.path), self.steplen)]
        return type(self).objects.filter(path__in=prefixes).order_by("path")

    def children_list(self):
        """Прямые потомки (активные), в порядке дерева."""
        return (type(self).objects
                .filter(path__startswith=self.path, depth=self.depth + 1, is_active=True)
                .order_by("path"))

    def leaf_descendant_ids(self):
        """pk всех конечных категорий в поддереве (включая саму себя, если она лист)."""
        if self.numchild == 0:
            return [self.pk]
        return list(
            type(self).objects
            .filter(path__startswith=self.path, numchild=0)
            .values_list("pk", flat=True)
        )

    def product_scope(self):
        """Товары в этой категории и во всех её подкатегориях."""
        return Product.objects.active().filter(category_id__in=self.leaf_descendant_ids())

    def get_attribute_schema(self):
        """
        {attribute.code: CategoryAttribute} для этой категории + всех предков.
        Если характеристика задана на нескольких уровнях, побеждает самый глубокий.
        """
        ancestor_ids = self.ancestor_ids()
        links = (
            CategoryAttribute.objects
            .filter(category_id__in=[*ancestor_ids, self.pk], attribute__is_active=True)
            .select_related("attribute", "category")
            .prefetch_related("attribute__options")
            .order_by("category__depth", "sort_order", "attribute__name")
        )
        schema = {}
        for link in links:  # от корня к листу -> более глубокий перезаписывает
            schema[link.attribute.code] = link
        return schema


# --------------------------------------------------------------------------
# Характеристики (то, что клиент добавляет сам)
# --------------------------------------------------------------------------
code_validator = RegexValidator(
    r"^[a-z][a-z0-9_]*$",
    "Только латиница в нижнем регистре, цифры и _, начинается с буквы.",
)


class Attribute(models.Model):
    class DataType(models.TextChoices):
        TEXT = "text", "Текст"
        INTEGER = "int", "Целое число"
        DECIMAL = "decimal", "Число (дробное)"
        BOOLEAN = "bool", "Да / Нет"
        CHOICE = "choice", "Выбор из списка (одно значение)"
        MULTI = "multi", "Выбор из списка (несколько значений)"

    name = models.CharField("Название", max_length=128)  # «Диаметр»
    code = models.CharField(
        "Код", max_length=64, unique=True, blank=True, validators=[code_validator],
        help_text="Ключ в JSON. Оставьте пустым — создастся автоматически. "
                  "После создания не меняется.",
    )
    data_type = models.CharField("Тип", max_length=16, choices=DataType.choices)
    unit = models.CharField("Ед. измерения", max_length=16, blank=True)  # мм, °, HRC
    is_active = models.BooleanField("Активна", default=True)

    class Meta:
        verbose_name = "Характеристика"
        verbose_name_plural = "Характеристики"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name}, {self.unit}" if self.unit else self.name

    @property
    def has_options(self):
        return self.data_type in (self.DataType.CHOICE, self.DataType.MULTI)

    def save(self, *args, **kwargs):
        if not self.code:
            base = make_code(self.name, "a")
            code, i = base, 2
            while Attribute.objects.filter(code=code).exists():
                code, i = f"{base}_{i}", i + 1
            self.code = code
        super().save(*args, **kwargs)


class AttributeOption(models.Model):
    attribute = models.ForeignKey(Attribute, on_delete=models.CASCADE, related_name="options")
    code = models.CharField("Код", max_length=64, blank=True, validators=[code_validator])
    label = models.CharField("Подпись", max_length=128)  # «Сталь», «Алюминий»
    sort_order = models.PositiveIntegerField("Порядок", default=0)

    class Meta:
        verbose_name = "Вариант значения"
        verbose_name_plural = "Варианты значений"
        ordering = ["sort_order", "label"]
        constraints = [
            models.UniqueConstraint(fields=["attribute", "code"], name="uniq_option_code_per_attr"),
        ]

    def __str__(self):
        return self.label

    def save(self, *args, **kwargs):
        if not self.code:
            base = make_code(self.label, "o")
            code, i = base, 2
            siblings = AttributeOption.objects.filter(attribute_id=self.attribute_id)
            while siblings.filter(code=code).exists():
                code, i = f"{base}_{i}", i + 1
            self.code = code
        super().save(*args, **kwargs)


class CategoryAttribute(models.Model):
    """Привязка характеристики к категории. Действует и на все дочерние."""
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="attribute_links")
    attribute = models.ForeignKey(Attribute, on_delete=models.PROTECT, related_name="category_links")
    is_required = models.BooleanField("Обязательна", default=False)
    is_filterable = models.BooleanField("Показывать в фильтре", default=True)
    sort_order = models.PositiveIntegerField("Порядок", default=0)

    class Meta:
        verbose_name = "Характеристика категории"
        verbose_name_plural = "Характеристики категории"
        ordering = ["sort_order"]
        constraints = [
            models.UniqueConstraint(fields=["category", "attribute"], name="uniq_attr_per_category"),
        ]

    def __str__(self):
        return f"{self.category} → {self.attribute}"


# --------------------------------------------------------------------------
# Товар
# --------------------------------------------------------------------------
class Brand(models.Model):
    name = models.CharField("Бренд / производитель", max_length=128, unique=True)

    class Meta:
        verbose_name = "Бренд"
        verbose_name_plural = "Бренды"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ProductQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def filter_by_attributes(self, equals=None, ranges=None):
        """
        equals: {"tool_material": "r6m5", "coated": True, "work_materials": ["steel", "alu"]}
            -> jsonb @> (использует GIN-индекс). Для списков — «содержит все».
        ranges: {"diameter": (6, 10)}  — (min, max), любой край может быть None.
        """
        qs = self
        for code, value in (equals or {}).items():
            qs = qs.filter(attributes__contains={code: value})
        for code, (low, high) in (ranges or {}).items():
            if low is not None:
                qs = qs.filter(**{f"attributes__{code}__gte": low})
            if high is not None:
                qs = qs.filter(**{f"attributes__{code}__lte": high})
        return qs


class Product(SlugWithIdMixin, models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    brand = models.ForeignKey(Brand, null=True, blank=True, on_delete=models.PROTECT,
                              related_name="products")
    sku = models.CharField("Артикул", max_length=64, unique=True)
    name = models.CharField("Название", max_length=255)
    description = models.TextField("Описание", blank=True)
    # Целая цена в основных единицах валюты. NULL = «цена по запросу».
    price = models.PositiveIntegerField("Цена", null=True, blank=True,
                                        help_text="Пусто = цена по запросу")
    is_active = models.BooleanField("Показывать на сайте", default=True)

    attributes = models.JSONField("Характеристики", default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["category", "is_active"], name="product_cat_active_idx"),
            GinIndex(fields=["attributes"], name="product_attrs_gin", opclasses=["jsonb_path_ops"]),
        ]

    def __str__(self):
        return f"{self.sku} — {self.name}"

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("shop:product", args=[self.slug])

    # ---- валидация и нормализация JSON по схеме категории ----
    def clean(self):
        super().clean()
        if self.category_id is None:
            return
        if not self.category.is_leaf():
            raise ValidationError({"category": "Товар можно положить только в конечную категорию."})
        self.attributes = self.validate_attributes(self.attributes)

    def validate_attributes(self, raw):
        """Возвращает очищенный dict или бросает ValidationError({'attributes': [...]})."""
        T = Attribute.DataType
        schema = self.category.get_attribute_schema()
        raw = {k: v for k, v in (raw or {}).items() if v not in (None, "", [])}
        errors, clean = [], {}

        unknown = set(raw) - set(schema)
        if unknown:
            errors.append(f"Характеристики не относятся к категории: {', '.join(sorted(unknown))}")

        for code, link in schema.items():
            attr = link.attribute
            if code not in raw:
                if link.is_required:
                    errors.append(f"«{attr.name}»: обязательное поле")
                continue
            value = raw[code]
            try:
                if attr.data_type == T.TEXT:
                    clean[code] = str(value).strip()
                elif attr.data_type == T.INTEGER:
                    if isinstance(value, bool) or int(value) != float(value):
                        raise ValueError
                    clean[code] = int(value)
                elif attr.data_type == T.DECIMAL:
                    if isinstance(value, bool):
                        raise ValueError
                    # float, а не Decimal: Decimal не сериализуется в JSON
                    clean[code] = float(str(value).replace(",", "."))
                elif attr.data_type == T.BOOLEAN:
                    if not isinstance(value, bool):
                        raise ValueError
                    clean[code] = value
                elif attr.data_type == T.CHOICE:
                    if value not in {o.code for o in attr.options.all()}:
                        raise ValueError
                    clean[code] = value
                elif attr.data_type == T.MULTI:
                    allowed = {o.code for o in attr.options.all()}
                    if not isinstance(value, list) or not set(value) <= allowed:
                        raise ValueError
                    clean[code] = sorted(set(value))
            except (ValueError, TypeError):
                errors.append(f"«{attr.name}»: недопустимое значение «{value}»")

        if errors:
            raise ValidationError({"attributes": errors})
        return clean
