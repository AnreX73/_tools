"""
shop/admin.py

Форма товара в админке: поле «Характеристики» строится динамически по выбранной категории.
При смене категории фрагмент с полями подгружается через fetch (см. product_attributes.js),
введённые в остальные поля данные не теряются.
"""
import json

# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from adminsortable2.admin import SortableAdminBase, SortableInlineAdminMixin
from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.http import HttpResponse, JsonResponse
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from treebeard.admin import TreeAdmin
from treebeard.forms import movenodeform_factory

from .models import (
    Attribute, AttributeOption, Brand, Catalog, Category, CategoryAttribute, CategorySortRule,
    Product, ProductImage,
)
from .sorting import sort_field_choices

T = Attribute.DataType

from django.contrib import admin
from django_q.models import Task, Success, Failure, Schedule, OrmQ

for model in (Task, Success, Failure, Schedule, OrmQ):
    if admin.site.is_registered(model):
        admin.site.unregister(model)


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
    readonly_fields = ("slug", "created_at", "updated_at", "images_dropzone")
    fieldsets = (
        (None, {"fields": ("category", "sku", "name", "brand", "price", "is_active", "description")}),
        ("Изображения", {"fields": ("images_dropzone",)}),
        ("Характеристики", {"fields": ("attributes",)}),
        ("Служебное", {"fields": ("slug", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    class Media:
        js = (
            "vendor/dropzone.min.js",
            "shop/admin/product_attributes.js",
            "shop/admin/product_images.js",
        )
        css = {
            "all": (
                "vendor/dropzone.min.css",
                "shop/admin/product_images.css",
            )
        }

    def get_urls(self):
        custom = [
            path(
                "attributes-fields/",
                self.admin_site.admin_view(self.attributes_fields_view),
                name="shop_product_attributes_fields",
            ),
            path(
                "images-upload/",
                self.admin_site.admin_view(self.images_upload_view),
                name="shop_product_images_upload",
            ),
            path(
                "images/<int:image_id>/delete/",
                self.admin_site.admin_view(self.image_delete_view),
                name="shop_product_image_delete",
            ),
            path(
                "images/reorder/",
                self.admin_site.admin_view(self.images_reorder_view),
                name="shop_product_images_reorder",
            ),
        ]
        return custom + super().get_urls()

    @admin.display(description="Изображения товара")
    def images_dropzone(self, obj):
        if not obj or not obj.pk:
            return format_html('<p class="help">{}</p>', "Сначала сохраните товар, затем добавьте изображения.")
        images = obj.images.all()
        items = format_html_join(
            "",
            '<div class="product-image-existing" data-image-id="{}" data-url="{}">'
            '<img src="{}" alt=""><button type="button" class="product-image-remove" '
            'aria-label="Удалить изображение">×</button></div>',
            ((image.pk, image.image.url, image.image.url) for image in images),
        )
        return format_html(
            '<div id="product-images-dropzone" class="dropzone" data-product-id="{}" '
            'data-upload-url="{}" data-reorder-url="{}" data-delete-url="{}" '
            'data-csrf-cookie="csrftoken">'
            '<div class="dz-message">Перетащите изображения сюда или нажмите для выбора</div>'
            '</div><div id="product-images-existing" class="product-images-existing">{}</div>',
            obj.pk,
            reverse("admin:shop_product_images_upload", args=()),
            reverse("admin:shop_product_images_reorder", args=()),
            reverse("admin:shop_product_image_delete", args=(0,)).replace("/0/", "/{id}/"),
            items,
        )

    def _image_product(self, request, image_id):
        image = ProductImage.objects.select_related("product").filter(pk=image_id).first()  # type: ignore[attr-defined]
        if not image or not self.has_change_permission(request, image.product):
            raise PermissionDenied
        return image

    def images_upload_view(self, request):
        if request.method != "POST":
            return JsonResponse({"error": "Метод не поддерживается."}, status=405)
        product = Product.objects.filter(pk=_int(request.POST.get("product"))).first()
        if not product or not self.has_change_permission(request, product):
            raise PermissionDenied
        uploaded = request.FILES.get("file")
        if not uploaded:
            return JsonResponse({"error": "Файл не передан."}, status=400)
        if uploaded.size > 10 * 1024 * 1024:
            return JsonResponse({"error": "Изображение не должно быть больше 10 МБ."}, status=400)
        try:
            forms.ImageField().clean(uploaded, None)
        except ValidationError:
            return JsonResponse({"error": "Допустимы только корректные изображения."}, status=400)
        with transaction.atomic():  # type: ignore[misc]
            Product.objects.select_for_update().get(pk=product.pk)
            last_order = product.images.aggregate(value=Max("sort_order"))["value"]
            image = ProductImage.objects.create(  # type: ignore[attr-defined]
                product=product, image=uploaded,
                sort_order=0 if last_order is None else last_order + 1,
            )
        return JsonResponse({"id": image.pk, "url": image.image.url, "name": image.image.name})

    def image_delete_view(self, request, image_id):
        if request.method != "POST":
            return JsonResponse({"error": "Метод не поддерживается."}, status=405)
        image = self._image_product(request, image_id)
        image.delete()
        return JsonResponse({"ok": True})

    def images_reorder_view(self, request):
        if request.method != "POST":
            return JsonResponse({"error": "Метод не поддерживается."}, status=405)
        try:
            payload = json.loads(request.body)
            product_id = int(payload["product"])
            ids = [int(value) for value in payload["ids"]]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "Некорректный порядок изображений."}, status=400)
        product = Product.objects.filter(pk=product_id).first()
        if not product or not self.has_change_permission(request, product):
            raise PermissionDenied
        images = list(ProductImage.objects.filter(pk__in=ids).select_related("product"))  # type: ignore[attr-defined]
        if {image.pk for image in images} != set(ids) or any(image.product_id != product.pk for image in images):
            return JsonResponse({"error": "Изображения принадлежат другому товару."}, status=400)
        if len(ids) != len(set(ids)):
            return JsonResponse({"error": "Повторяющиеся изображения."}, status=400)
        by_id = {image.pk: image for image in images}
        for position, image_id in enumerate(ids):
            by_id[image_id].sort_order = position
        ProductImage.objects.bulk_update(images, ["sort_order"])  # type: ignore[attr-defined]
        return JsonResponse({"ok": True})

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
        return HttpResponse(widget.render("attributes", values))  # type: ignore[arg-type]


class CategoryAttributeInline(admin.TabularInline):
    model = CategoryAttribute
    extra = 0
    autocomplete_fields = ("attribute",)


class CategorySortRuleForm(forms.ModelForm):
    field = forms.ChoiceField(label="Сортировать по")

    class Meta:
        model = CategorySortRule
        fields = ["field", "descending"]


class CategorySortRuleInline(SortableInlineAdminMixin, admin.TabularInline):
    """Порядок выдачи товаров: строки перетаскиваются, верхнее правило главнее."""
    model = CategorySortRule
    form = CategorySortRuleForm
    extra = 0
    verbose_name = "правило сортировки"
    verbose_name_plural = ("Порядок выдачи товаров (перетаскивайте строки: верхнее правило "
                           "главнее; если пусто — берётся у родительской категории, "
                           "а если нигде не задано — по названию)")

    def get_formset(self, request, obj=None, **kwargs):
        # choices считаем один раз на весь формсет, а не на каждую строку
        choices = sort_field_choices()

        class Form(CategorySortRuleForm):
            def __init__(self, *args, **kw):
                super().__init__(*args, **kw)
                self.fields["field"].choices = choices

        kwargs["form"] = Form
        return super().get_formset(request, obj, **kwargs)


@admin.register(Category)
class CategoryAdmin(SortableAdminBase, TreeAdmin):
    form = movenodeform_factory(Category)
    list_display = ("name", "is_active")
    search_fields = ("name",)
    inlines = [CategoryAttributeInline, CategorySortRuleInline]
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

    def get_readonly_fields(self, request, obj=None):  # type: ignore[override]
        # код и тип менять после создания нельзя: на них завязаны сохранённые значения
        return ("code", "data_type") if obj else ()


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Catalog)
class CatalogAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "sort_order", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    autocomplete_fields = ("products", "categories", "brands")
    readonly_fields = ("slug", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("name", "description", "file", "cover", "is_active", "sort_order")}),
        ("Привязка", {"fields": ("products", "categories", "brands")}),
        ("Служебное", {"fields": ("slug", "created_at", "updated_at"), "classes": ("collapse",)}),
    )



admin.site.site_header = "Тулз сервис — админка"
admin.site.site_title = "Тулз сервис — админка"
