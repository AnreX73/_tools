"""
shop/management/commands/seed_shop.py

Заполняет БД демо-каталогом из shop/data/seed_shop.json:
характеристики -> дерево категорий (+ привязка характеристик) -> товары.

    python manage.py seed_shop              # добавить/обновить (идемпотентно)
    python manage.py seed_shop --flush      # сначала полностью очистить каталог
    python manage.py seed_shop --no-products
    python manage.py seed_shop --file /path/to/other.json

Идемпотентность: характеристики ищутся по code, варианты по (характеристика, code),
категории по (родитель, name), товары по sku. Повторный запуск ничего не дублирует.
Каждый товар проходит Product.clean(), т.е. ту же валидацию, что и форма в админке:
если JSON противоречит схеме категории — команда остановится с понятной ошибкой
и откатит всё (одна транзакция).
"""
import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from shop.models import (
    Attribute, AttributeOption, Brand, Category, CategoryAttribute, Product,
)

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "data" / "seed_shop.json"


class Command(BaseCommand):
    help = "Заполняет БД демо-каталогом (категории, характеристики, товары) из seed_shop.json"

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(DEFAULT_FILE), help="Путь к JSON (по умолчанию shop/data/seed_shop.json)")
        parser.add_argument("--flush", action="store_true", help="Удалить ВСЕ товары, категории, характеристики и бренды перед загрузкой")
        parser.add_argument("--no-products", action="store_true", help="Загрузить только дерево и характеристики")

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        path = Path(opts["file"])
        if not path.exists():
            raise CommandError(f"Файл не найден: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise CommandError(f"Некорректный JSON ({path.name}): {e}")

        self.stats = {"attributes": 0, "options": 0, "categories": 0, "links": 0, "products": 0, "brands": 0}
        self.skip_products = opts["no_products"]
        self.brands = {}

        with transaction.atomic():
            if opts["flush"]:
                self._flush()
            self.attributes = self._load_attributes(data.get("attribute_definitions", []))
            for node in data.get("categories", []):
                self._load_category(node, parent=None)

        s = self.stats
        self.stdout.write(self.style.SUCCESS(
            f"Готово: характеристик +{s['attributes']}, вариантов +{s['options']}, "
            f"категорий +{s['categories']}, привязок +{s['links']}, брендов +{s['brands']}, товаров +{s['products']} "
            f"(числа — только новые записи; существующие обновлены)."
        ))

    # ------------------------------------------------------------------
    def _flush(self):
        # порядок важен: Product/CategoryAttribute держат PROTECT на остальные
        Product.objects.all().delete()
        Category.objects.all().delete()      # CategoryAttribute уходит каскадом
        Attribute.objects.all().delete()     # AttributeOption — каскадом
        Brand.objects.all().delete()
        self.stdout.write(self.style.WARNING("Каталог очищен."))

    # ------------------------------------------------------------------
    def _load_attributes(self, items):
        result = {}
        for item in items:
            attr, created = Attribute.objects.update_or_create(
                code=item["code"],
                defaults={
                    "name": item["name"],
                    "data_type": item["data_type"],
                    "unit": item.get("unit", ""),
                    "is_active": True,
                },
            )
            self.stats["attributes"] += created
            for order, opt in enumerate(item.get("options", [])):
                _, created = AttributeOption.objects.update_or_create(
                    attribute=attr, code=opt["code"],
                    defaults={"label": opt["label"], "sort_order": order},
                )
                self.stats["options"] += created
            result[attr.code] = attr
        return result

    # ------------------------------------------------------------------
    # Работа с деревом — через path/depth: не зависит от версии treebeard
    # (в 7.x методы add_root/add_child/get_children переехали в менеджер).
    def _find_node(self, name, parent):
        if parent is None:
            qs = Category.objects.filter(depth=1, name=name)
        else:
            qs = Category.objects.filter(path__startswith=parent.path, depth=parent.depth + 1, name=name)
        return qs.first()

    def _create_node(self, name, parent):
        mgr = Category.objects
        if parent is None:
            if hasattr(mgr, "add_root"):           # treebeard >= 7
                return mgr.add_root(create_kwargs={"name": name})
            return Category.add_root(name=name)
        parent.refresh_from_db()                    # актуальные numchild/path
        if hasattr(mgr, "add_child"):
            return mgr.add_child(parent, create_kwargs={"name": name})
        return parent.add_child(name=name)

    def _load_category(self, node, parent):
        category = self._find_node(node["name"], parent)
        if category is None:
            category = self._create_node(node["name"], parent)
            self.stats["categories"] += 1

        for order, link in enumerate(node.get("attributes", [])):
            code = link["code"]
            if code not in self.attributes:
                raise CommandError(f"Категория «{node['name']}»: неизвестная характеристика «{code}»")
            _, created = CategoryAttribute.objects.update_or_create(
                category=category, attribute=self.attributes[code],
                defaults={
                    "is_required": link.get("required", False),
                    "is_filterable": link.get("filterable", True),
                    "sort_order": order,
                },
            )
            self.stats["links"] += created

        children = node.get("children", [])
        products = node.get("products", [])
        if children and products:
            raise CommandError(f"Категория «{node['name']}»: товары можно класть только в конечные категории")

        for child in children:
            self._load_category(child, category)

        if products and not self.skip_products:
            category.refresh_from_db()
            for item in products:
                self._load_product(category, item)

    # ------------------------------------------------------------------
    def _brand(self, name):
        if not name:
            return None
        if name not in self.brands:
            brand, created = Brand.objects.get_or_create(name=name)
            self.stats["brands"] += created
            self.brands[name] = brand
        return self.brands[name]

    def _load_product(self, category, item):
        product = Product.objects.filter(sku=item["sku"]).first()
        created = product is None
        if created:
            product = Product(sku=item["sku"])

        product.category = category
        product.name = item["name"]
        product.brand = self._brand(item.get("brand"))
        product.price = item.get("price")             # int или null («цена по запросу»)
        product.description = item.get("description", "")
        product.is_active = item.get("is_active", True)
        product.attributes = item.get("attributes", {})

        try:
            product.clean()   # проверка по схеме категории + нормализация значений
        except ValidationError as e:
            raise CommandError(f"Товар {item['sku']} «{item['name']}»: {e.message_dict if hasattr(e, 'error_dict') else e.messages}")
        product.save()
        self.stats["products"] += created
