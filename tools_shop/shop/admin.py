"""
shop/admin.py

Форма товара в админке: поле «Характеристики» строится динамически по выбранной категории.
При смене категории фрагмент с полями подгружается через fetch (см. product_attributes.js),
введённые в остальные поля данные не теряются.
"""
from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from treebeard.admin import TreeAdmin
from treebeard.forms import movenodeform_factory

from .models import (
    Attribute, AttributeOption, Brand, Category, CategoryAttribute, Product,
)

T = Attribute.DataType


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Виджет и поле «Характеристики»
# --------------------------------------------------------------------------
class AttributesWidget(forms.Widget):
    """
    Рисует по одному input на каждую характеристику категории.
    Имена полей: attributes__<code>. Собирает их обратно в dict.
    Список характеристик (self.links) задаёт форма в __init__.
    """

    def __init__(self, attrs=None):
        super().__init__(attrs)
        self.links = []        # list[CategoryAttribute]
        self.product_id = None

    # --- какие input'ы использовать ---
    @staticmethod
    def _subwidget(attr):
        options = [(o.code, o.label) for o in attr.options.all()]
        if attr.data_type == T.INTEGER:
            return forms.NumberInput(attrs={"step": 1})
        if attr.data_type == T.DECIMAL:
            return forms.NumberInput(attrs={"step": "any"})
        if attr.data_type == T.BOOLEAN:
            return forms.Select(choices=[("", "—"), ("true", "Да"), ("false", "Нет")])
        if attr.data_type == T.CHOICE:
            return forms.Select(choices=[("", "—"), *options])
        if attr.data_type == T.MULTI:
            return forms.CheckboxSelectMultiple(choices=options)
        return forms.TextInput(attrs={"class": "vTextField"})

    @staticmethod
    def _prepare(attr, value):
        if value is None:
            return None
        if attr.data_type == T.BOOLEAN:
            return "true" if value is True or value == "true" else "false"
        if attr.data_type == T.DECIMAL and isinstance(value, float) and value.is_integer():
            return int(value)
        return value

    # --- рендер ---
    def render(self, name, value, attrs=None, renderer=None):
        value = value if isinstance(value, dict) else {}
        rows = []
        for link in self.links:
            attr = link.attribute
            sub_name = f"{name}__{attr.code}"
            sub_id = f"id_{sub_name}"
            widget = self._subwidget(attr)
            control = widget.render(
                sub_name, self._prepare(attr, value.get(attr.code)), {"id": sub_id}, renderer
            )
            label = attr.name
            if attr.unit:
                label += f", {attr.unit}"
            if link.is_required:
                label += " *"
            rows.append((format_html(
                '<div style="display:flex;gap:12px;align-items:baseline;margin:6px 0">'
                '<label for="{}" style="min-width:230px;font-weight:600">{}</label><div>{}</div></div>',
                sub_id, label, control,
            ),))
        if rows:
            body = format_html_join("", "{}", rows)
        else:
            body = format_html(
                '<p class="help">{}</p>',
                "Выберите категорию — здесь появятся её характеристики."
                if not self.links else "",
            )
        return format_html(
            '<div id="attributes-box" data-url="{}" data-product-id="{}">{}</div>',
            reverse("admin:shop_product_attributes_fields"),
            self.product_id or "",
            body,
        )

    # --- сбор данных из POST ---
    def value_from_datadict(self, data, files, name):
        result = {}
        for link in self.links:
            attr = link.attribute
            key = f"{name}__{attr.code}"
            if attr.data_type == T.MULTI:
                values = data.getlist(key)
                if values:
                    result[attr.code] = values
                continue
            raw = data.get(key, "")
            if raw == "":
                continue
            if attr.data_type == T.BOOLEAN:
                raw = {"true": True, "false": False}.get(raw)
                if raw is None:
                    continue
            result[attr.code] = raw
        return result

    def value_omitted_from_data(self, data, files, name):
        # Ключа "attributes" в POST нет (есть attributes__<code>), но поле ВСЕГДА
        # присутствует в форме. Иначе Django пропустит пустой dict и не сотрёт старые значения.
        return False

    def id_for_label(self, id_):
        return None


class AttributesField(forms.Field):
    widget = AttributesWidget

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)

    def clean(self, value):
        # Проверка по схеме категории — в Product.clean(), ошибки попадут сюда же
        return value or {}


# --------------------------------------------------------------------------
# Форма товара
# --------------------------------------------------------------------------
class ProductAdminForm(forms.ModelForm):
    attributes = AttributesField(label="Характеристики")

    class Meta:
        model = Product
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Только конечные категории, подписи — полный путь одним запросом
        nodes = list(Category.objects.all())  # MP_Node сортирует по path
        by_path = {n.path: n.name for n in nodes}
        step = Category.steplen
        labels = {
            n.pk: " / ".join(by_path[n.path[:i]] for i in range(step, len(n.path) + 1, step))
            for n in nodes if n.numchild == 0
        }
        field = self.fields["category"]
        field.queryset = Category.objects.filter(numchild=0)
        field.label_from_instance = lambda c: labels.get(c.pk, c.name)

        widget = self.fields["attributes"].widget
        category = self._current_category()
        widget.links = list(category.get_attribute_schema().values()) if category else []
        widget.product_id = self.instance.pk

    def _current_category(self):
        if self.is_bound:
            raw = self.data.get(self.add_prefix("category"))
        else:  # у существующего товара — его категория; на add — ?category=<id> из URL
            raw = self.initial.get("category")
        pk = _int(raw)
        return Category.objects.filter(pk=pk).first() if pk else None


# --------------------------------------------------------------------------
# Админки
# --------------------------------------------------------------------------
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = ("sku", "name", "category", "price", "is_active")
    list_filter = ("is_active", "brand", ("category", admin.RelatedOnlyFieldListFilter))
    list_select_related = ("category",)
    search_fields = ("sku", "name")
    readonly_fields = ("slug", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("category", "sku", "name", "brand", "price", "is_active", "description", "image")}),
        ("Характеристики", {"fields": ("attributes",)}),
        ("Служебное", {"fields": ("slug", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    class Media:
        js = ("shop/admin/product_attributes.js",)

    def get_urls(self):
        custom = [
            path(
                "attributes-fields/",
                self.admin_site.admin_view(self.attributes_fields_view),
                name="shop_product_attributes_fields",
            ),
        ]
        return custom + super().get_urls()

    def attributes_fields_view(self, request):
        """Фрагмент с полями характеристик для выбранной категории (вызывается из JS)."""
        if not (self.has_view_or_change_permission(request) or self.has_add_permission(request)):
            raise PermissionDenied
        category = Category.objects.filter(pk=_int(request.GET.get("category")), numchild=0).first()
        product = Product.objects.filter(pk=_int(request.GET.get("product"))).first()
        # значения подставляем, только если категория та же, что сохранена у товара
        values = product.attributes if (product and category and product.category_id == category.pk) else {}

        widget = AttributesWidget()
        widget.product_id = product.pk if product else None
        widget.links = list(category.get_attribute_schema().values()) if category else []
        return HttpResponse(widget.render("attributes", values))


class CategoryAttributeInline(admin.TabularInline):
    model = CategoryAttribute
    extra = 0
    autocomplete_fields = ("attribute",)


@admin.register(Category)
class CategoryAdmin(TreeAdmin):
    form = movenodeform_factory(Category)
    list_display = ("name", "is_active")
    search_fields = ("name",)
    inlines = [CategoryAttributeInline]
    readonly_fields = ("slug", "inherited_attributes")

    @admin.display(description="Унаследованные характеристики")
    def inherited_attributes(self, obj):
        if not obj.pk:
            return "—"
        links = (CategoryAttribute.objects
                 .filter(category_id__in=obj.ancestor_ids())
                 .select_related("attribute", "category"))
        return format_html_join(
            ", ", "{} (из «{}»)",
            ((link.attribute, link.category) for link in links),
        ) or "—"


class AttributeOptionInline(admin.TabularInline):
    model = AttributeOption
    extra = 1
    fields = ("label", "sort_order")   # код генерируется автоматически


@admin.register(Attribute)
class AttributeAdmin(admin.ModelAdmin):
    list_display = ("name", "unit", "data_type", "code", "is_active")
    list_filter = ("data_type", "is_active")
    search_fields = ("name", "code")   # нужно для autocomplete в CategoryAdmin
    inlines = [AttributeOptionInline]

    def get_readonly_fields(self, request, obj=None):
        # код и тип менять после создания нельзя: на них завязаны сохранённые значения
        return ("code", "data_type") if obj else ()


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    search_fields = ("name",)



admin.site.site_header = "Тулз сервис — админка"
admin.site.site_title = "Тулз сервис — админка"