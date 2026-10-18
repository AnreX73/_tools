"""
Тесты каталога: дерево, характеристики, фильтры и slug.

Запуск (нужен PostgreSQL):
    python manage.py test shop
"""
# Django's dynamic ORM and test-client APIs are not fully represented by the
# project's pyright stubs.
# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.http import QueryDict
from django.test import TestCase

from . import catalog
from .models import Attribute, AttributeOption, Category, CategoryAttribute, PopupNotice, Product

T = Attribute.DataType


class CatalogTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = Category.objects.add_root(
            create_kwargs={"name": "Металлорежущий инструмент"}
        )
        cls.leaf = Category.objects.add_child(cls.root, create_kwargs={"name": "Свёрла"})

        cls.material = Attribute.objects.create(
            name="Материал инструмента", code="tool_material", data_type=T.CHOICE
        )
        AttributeOption.objects.create(attribute=cls.material, code="r6m5", label="Р6М5")
        AttributeOption.objects.create(attribute=cls.material, code="carbide", label="Твёрдый сплав")

        cls.work = Attribute.objects.create(
            name="Обрабатываемый материал", code="work_materials", data_type=T.MULTI
        )
        AttributeOption.objects.create(attribute=cls.work, code="steel", label="Сталь")
        AttributeOption.objects.create(attribute=cls.work, code="aluminium", label="Алюминий")

        cls.diameter = Attribute.objects.create(
            name="Диаметр", code="diameter", data_type=T.DECIMAL, unit="мм"
        )

        # общие характеристики — на корне, диаметр — на листе
        CategoryAttribute.objects.create(category=cls.root, attribute=cls.material, is_filterable=True)
        CategoryAttribute.objects.create(category=cls.root, attribute=cls.work, is_filterable=True)
        CategoryAttribute.objects.create(category=cls.leaf, attribute=cls.diameter, is_filterable=True)

        cls.p1 = cls._product("DR-001", "Сверло Ø6,0 мм", {"tool_material": "r6m5",
                                                          "work_materials": ["steel"],
                                                          "diameter": 6.0})
        cls.p2 = cls._product("DR-002", "Сверло Ø8,0 мм", {"tool_material": "r6m5",
                                                          "work_materials": ["steel", "aluminium"],
                                                          "diameter": 8.0})
        cls.p3 = cls._product("DR-003", "Сверло Ø12,0 мм", {"tool_material": "carbide",
                                                            "work_materials": ["aluminium"],
                                                            "diameter": 12.0})

    @classmethod
    def _product(cls, sku, name, attributes):
        product = Product(sku=sku, name=name, category=cls.leaf, price=100, attributes=attributes)
        product.full_clean()
        product.save()
        return product

    # ---- цена ----
    def test_active_product_requires_price(self):
        product = Product(
            sku="NO-PRICE", name="Товар без цены", category=self.leaf,
            is_active=True, attributes={},
        )
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_inactive_product_may_have_no_price(self):
        product = Product(
            sku="HIDDEN", name="Скрытый товар", category=self.leaf,
            is_active=False, attributes={},
        )
        product.full_clean()

    # ---- slug ----
    def test_slug_is_ascii_for_diameter_symbol(self):
        self.assertTrue(self.p1.slug.isascii(), self.p1.slug)
        self.assertNotIn("ø", self.p1.slug.lower())
        # и URL реально резолвится
        self.assertTrue(self.p1.get_absolute_url().startswith("/product/"))

    # ---- дерево ----
    def test_schema_is_inherited_from_ancestors(self):
        schema = self.leaf.get_attribute_schema()
        self.assertEqual(set(schema), {"tool_material", "work_materials", "diameter"})

    def test_root_scope_includes_leaf_products(self):
        self.assertEqual(self.root.product_scope().count(), 3)

    # ---- страницы ----
    def test_category_page_and_htmx_partial(self):
        url = self.leaf.get_absolute_url()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="catalog-body"')

        partial = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(partial.status_code, 200)
        self.assertNotContains(partial, "<html")
        self.assertContains(partial, 'id="catalog-body"')

    def test_product_page(self):
        response = self.client.get(self.p1.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Материал инструмента")

    # ---- фильтры ----
    def _ids(self, response):
        return {p["product"].pk for p in response.context["products"]}

    def test_choice_filter(self):
        response = self.client.get(self.leaf.get_absolute_url(), {"a__tool_material": "r6m5"})
        self.assertEqual(self._ids(response), {self.p1.pk, self.p2.pk})

    def test_multi_filter_is_or_within_attribute(self):
        base = self.leaf.get_absolute_url()
        self.assertEqual(
            self._ids(self.client.get(base, {"a__work_materials": "steel"})),
            {self.p1.pk, self.p2.pk},
        )
        self.assertEqual(
            self._ids(self.client.get(base, {"a__work_materials": ["steel", "aluminium"]})),
            {self.p1.pk, self.p2.pk, self.p3.pk},
        )

    def test_range_filter(self):
        response = self.client.get(
            self.leaf.get_absolute_url(), {"a__diameter__min": "7", "a__diameter__max": "10"}
        )
        self.assertEqual(self._ids(response), {self.p2.pk})

    def test_unknown_filter_value_is_ignored(self):
        response = self.client.get(self.leaf.get_absolute_url(), {"a__tool_material": "nope"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._ids(response), {self.p1.pk, self.p2.pk, self.p3.pk})

    # ---- фасеты ----
    def _facet(self, facets, code):
        return next(f for f in facets if f["code"] == code)

    def test_facet_counts_exclude_own_filter(self):
        schema = self.leaf.get_attribute_schema()
        state = catalog.parse_filters(QueryDict("a__work_materials=steel"), schema)
        facets = catalog.build_facets(self.leaf.product_scope(), schema, state)

        work = self._facet(facets, "work_materials")
        counts = {o["code"]: o["count"] for o in work["options"]}
        # выбран steel, но счётчики остальных значений не обнуляются
        self.assertEqual(counts, {"steel": 2, "aluminium": 2})

        material = self._facet(facets, "tool_material")
        counts = {o["code"]: o["count"] for o in material["options"]}
        self.assertEqual(counts, {"r6m5": 2, "carbide": 0})

    def test_range_facet_bounds(self):
        schema = self.leaf.get_attribute_schema()
        facets = catalog.build_facets(self.leaf.product_scope(), schema, catalog.FilterState())
        diameter = self._facet(facets, "diameter")
        self.assertEqual((diameter["min"], diameter["max"]), (6, 12))

    # ---- админская форма характеристик ----
    def test_admin_attributes_fields_endpoint(self):
        user = get_user_model().objects.create_superuser(username="admin", password="test-only")  # noqa: S106
        self.client.force_login(user)
        response = self.client.get(
            "/admin/shop/product/attributes-fields/", {"category": self.leaf.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "attributes__diameter")
        self.assertContains(response, "attributes__tool_material")

    # ---- десктоп: каскадная навигация и инлайн-карточка товара ----
    def test_category_page_passes_cascade_path(self):
        response = self.client.get(self.leaf.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["cascade_path"], [self.root.slug, self.leaf.slug])
        self.assertIn(self.root, list(response.context["root_categories"]))
        self.assertContains(response, 'id="cascade-columns"')

        # htmx-загрузка не затронута — отдаёт тот же мобильный партиал, без cascade_path
        partial = self.client.get(self.leaf.get_absolute_url(), HTTP_HX_REQUEST="true")
        self.assertNotIn("cascade_path", partial.context)

    def test_cascade_root_endpoint(self):
        response = self.client.get("/cascade/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<html")
        self.assertContains(response, self.root.name)
        self.assertContains(response, f'hx-get="/cascade/{self.root.slug}/"')

    def test_cascade_level_non_leaf_returns_children(self):
        response = self.client.get(f"/cascade/{self.root.slug}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'id="cascade-col-{self.root.depth}"')
        self.assertContains(response, self.leaf.name)

    def test_cascade_toggle_closes_on_repeat_click_is_pure_client_state(self):
        # Сервер не знает про раскрыто/свёрнуто — проверяем, что каждая кнопка
        # узла в ответе уникальна (нет дублирующего узла с тем же hx-get в ответе),
        # иначе cascadeNav.toggle на клиенте не сможет надёжно отследить is-active.
        response = self.client.get(f"/cascade/{self.root.slug}/")
        self.assertEqual(
            response.content.decode().count(f'hx-get="/cascade/{self.leaf.slug}/"'), 1
        )

    def test_cascade_level_leaf_returns_products(self):
        response = self.client.get(f"/cascade/{self.leaf.slug}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'id="cascade-col-{self.leaf.depth}"')
        self.assertContains(response, self.p1.sku)
        self.assertContains(response, self.p2.sku)
        self.assertContains(response, self.p3.sku)

    def test_product_card_endpoint(self):
        response = self.client.get(f"/product/{self.p1.slug}/card/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<html")
        self.assertContains(response, "В корзину")
        self.assertContains(response, self.p1.get_absolute_url())

    def test_index_page_has_desktop_rail_and_mobile_tiles(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="cascade-columns"')
        self.assertContains(response, 'class="cascade-rail"')
        self.assertContains(response, 'class="hero"')
        self.assertContains(response, self.root.name)


class SearchTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        from .models import Brand

        cls.root = Category.objects.add_root(create_kwargs={"name": "Металлорежущий инструмент"})
        cls.leaf = Category.objects.add_child(cls.root, create_kwargs={"name": "Свёрла по металлу"})
        cls.other = Category.objects.add_child(cls.root, create_kwargs={"name": "Фрезы"})
        brand = Brand.objects.create(name="Bosch")

        def make(sku, name, category, **extra):
            return Product.objects.create(sku=sku, name=name, category=category, **extra)

        cls.drill6 = make("DR-001", "Сверло спиральное Ø6,0 мм", cls.leaf, brand=brand, price=120)
        cls.drill8 = make("DR-002", "Сверло спиральное Ø8,0 мм", cls.leaf, price=180)
        cls.mill = make("ML-100", "Фреза концевая твёрдосплавная", cls.other, price=950)
        cls.hidden = make("DR-999", "Сверло скрытое", cls.leaf, is_active=False)

    def _ids(self, query):
        from . import search
        return [p.pk for p in search.search_products(query)]

    def test_all_words_required_any_order_and_case(self):
        self.assertEqual(self._ids("6,0 СВЕРЛО"), [self.drill6.pk])
        self.assertEqual(set(self._ids("сверло")), {self.drill6.pk, self.drill8.pk})

    def test_decimal_comma_equals_dot(self):
        self.assertEqual(self._ids("сверло 6.0"), [self.drill6.pk])
        self.assertEqual(self._ids("сверло 6,0"), [self.drill6.pk])

    def test_yo_is_e(self):
        self.assertEqual(self._ids("твердосплавная"), [self.mill.pk])
        self.assertEqual(self._ids("твёрдосплавная"), [self.mill.pk])

    def test_sku_without_separators_and_ranking(self):
        self.assertEqual(self._ids("dr001"), [self.drill6.pk])
        # точное совпадение артикула — первым
        self.assertEqual(self._ids("DR-002")[0], self.drill8.pk)

    def test_brand_and_inactive(self):
        self.assertEqual(self._ids("bosch"), [self.drill6.pk])
        self.assertNotIn(self.hidden.pk, self._ids("скрытое"))

    def test_short_query_returns_nothing(self):
        self.assertEqual(self._ids("с"), [])

    def test_like_wildcards_are_literal(self):
        self.assertEqual(self._ids("%%"), [])
        self.assertEqual(self._ids("__"), [])

    def test_categories(self):
        from . import search
        self.assertEqual(search.search_categories("сверла"), [self.leaf])

    def test_suggest_endpoint(self):
        response = self.client.get("/search/suggest/", {"q": "сверло"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<html")
        self.assertContains(response, "<mark>Сверло</mark>", count=2)
        self.assertContains(response, "/search/?q=%D1%81%D0%B2%D0%B5%D1%80%D0%BB%D0%BE")

        empty = self.client.get("/search/suggest/", {"q": "х"})
        self.assertEqual(empty.content.strip(), b"")

        nothing = self.client.get("/search/suggest/", {"q": "несуществующее"})
        self.assertContains(nothing, "Ничего не нашлось")

    def test_highlight_escapes_html(self):
        from .templatetags.shop_search import highlight
        self.assertEqual(highlight("<b>Сверло</b>", "сверло"), "&lt;b&gt;<mark>Сверло</mark>&lt;/b&gt;")
        self.assertEqual(highlight("Твёрдый", "твердый"), "<mark>Твёрдый</mark>")
        self.assertEqual(highlight("Ø0.20 мм", "0,20"), "Ø<mark>0.20</mark> мм")

    def test_results_page(self):
        response = self.client.get("/search/", {"q": "сверло"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total"], 2)
        self.assertContains(response, 'value="сверло"')
        self.assertContains(response, "Свёрла по металлу")  # категория на карточке

        for q in ("", "с"):
            self.assertEqual(self.client.get("/search/", {"q": q}).status_code, 200)

    def test_results_page_breadcrumb_for_desktop_rows(self):
        response = self.client.get("/search/", {"q": "сверло"})
        breadcrumb_map = {
            item["product"].pk: item["breadcrumb"] for item in response.context["products"]
        }
        self.assertEqual(
            breadcrumb_map[self.drill6.pk],
            [self.root.name, self.leaf.name],
        )
        self.assertContains(response, "Металлорежущий инструмент → Свёрла по металлу")


class PopupNoticeTestCase(TestCase):
    """Всплывающее окно при входе на сайт."""

    def test_get_active_returns_active_and_none_when_inactive(self):
        self.assertIsNone(PopupNotice.get_active())
        popup = PopupNotice.objects.create(title="Акция", is_active=True)
        self.assertEqual(PopupNotice.get_active(), popup)

        popup.is_active = False
        popup.save()
        self.assertIsNone(PopupNotice.get_active())

    def test_only_one_active_row_is_kept_by_save(self):
        first = PopupNotice.objects.create(title="Первое", is_active=True)
        second = PopupNotice.objects.create(title="Второе", is_active=True)
        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertEqual(PopupNotice.objects.filter(is_active=True).get(), second)

    def test_db_constraint_blocks_two_active_rows(self):
        PopupNotice.objects.create(title="Первое", is_active=True)
        second = PopupNotice.objects.create(title="Второе", is_active=False)
        # bulk update обходит save() — ограничение ловит уже сама БД
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PopupNotice.objects.filter(pk=second.pk).update(is_active=True)

    def test_empty_active_popup_is_not_shown(self):
        PopupNotice.objects.create(is_active=True)  # все содержательные поля пусты
        self.assertIsNone(PopupNotice.get_active())

    def test_popup_rendered_on_site_only_when_active(self):
        self.assertNotContains(self.client.get("/"), 'id="site-popup"')

        popup = PopupNotice.objects.create(
            title="Скидки", text="Скидки на свёрла", button_text="В каталог",
            button_url="/catalog/", is_active=True,
        )
        response = self.client.get("/")
        self.assertContains(response, 'id="site-popup"')
        self.assertContains(response, "Скидки на свёрла")
        self.assertContains(response, f'data-popup-id="{popup.pk}"')
        self.assertContains(response, 'href="/catalog/"')

    def test_admin_deactivates_previous_active_popup(self):
        first = PopupNotice.objects.create(title="Первое", is_active=True)
        user = get_user_model().objects.create_superuser(
            username="popup-admin", password="test-only",  # noqa: S106
        )
        self.client.force_login(user)
        response = self.client.post(
            "/admin/shop/popupnotice/add/",
            {"title": "Второе", "text": "", "button_text": "", "button_url": "", "is_active": "on"},
        )
        self.assertEqual(response.status_code, 302)
        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertEqual(PopupNotice.objects.filter(is_active=True).count(), 1)


class RaisePricesCommandTestCase(TestCase):
    """Команда raise_prices: наценка процентом и заглушка с единой ценой."""

    @classmethod
    def setUpTestData(cls):
        root = Category.objects.add_root(create_kwargs={"name": "Инструмент"})
        cls.leaf = Category.objects.add_child(root, create_kwargs={"name": "Свёрла"})
        cls.cheap = cls._product("RP-100", 100)
        cls.rounds = cls._product("RP-4098", 4098)
        cls.hidden = cls._product("RP-300", 300, is_active=False)
        cls.zero = cls._product("RP-0", 0, is_active=False)
        cls.no_price = cls._product("RP-NONE", None, is_active=False)

    @classmethod
    def _product(cls, sku, price, is_active=True):
        return Product.objects.create(
            sku=sku, name=f"Товар {sku}", category=cls.leaf,
            price=price, is_active=is_active, attributes={},
        )

    def _run(self, *args):
        out = StringIO()
        call_command("raise_prices", *args, stdout=out)
        return out.getvalue()

    def _prices(self):
        return dict(Product.objects.values_list("sku", "price"))

    # ---- режим процентов ----
    def test_default_percent_raises_prices_by_15(self):
        self._run()
        prices = self._prices()
        self.assertEqual(prices["RP-100"], 115)
        self.assertEqual(prices["RP-4098"], 4713)  # 4098 * 1.15 = 4712.7
        self.assertEqual(prices["RP-300"], 345)    # скрытый товар тоже
        self.assertEqual(prices["RP-0"], 0)
        self.assertIsNone(prices["RP-NONE"])

    def test_percent_is_configurable(self):
        self._run("--percent", "10")
        self.assertEqual(self._prices()["RP-100"], 110)

    def test_dry_run_changes_nothing(self):
        output = self._run("--dry-run")
        self.assertIn("Dry-run", output)
        self.assertEqual(self._prices()["RP-100"], 100)
        self.assertEqual(self._prices()["RP-4098"], 4098)

    def test_updated_at_is_touched(self):
        before = Product.objects.get(sku="RP-100").updated_at
        self._run()
        self.assertGreater(Product.objects.get(sku="RP-100").updated_at, before)

    # ---- заглушка с единой ценой ----
    def test_fixed_price_requires_yes(self):
        output = self._run("--fixed-price", "777")
        self.assertIn("--yes", output)
        self.assertEqual(self._prices()["RP-100"], 100)
        self.assertEqual(self._prices()["RP-4098"], 4098)

    def test_fixed_price_sets_same_price_for_all_priced_products(self):
        self._run("--fixed-price", "777", "--yes")
        prices = self._prices()
        self.assertEqual(prices["RP-100"], 777)
        self.assertEqual(prices["RP-4098"], 777)
        self.assertEqual(prices["RP-300"], 777)
        # без цены и с ценой 0 остаются нетронутыми
        self.assertEqual(prices["RP-0"], 0)
        self.assertIsNone(prices["RP-NONE"])

    def test_fixed_price_dry_run_does_not_write(self):
        self._run("--fixed-price", "777", "--dry-run")
        self.assertEqual(self._prices()["RP-100"], 100)

    def test_negative_fixed_price_is_rejected(self):
        with self.assertRaises(CommandError):
            self._run("--fixed-price", "-1", "--yes")

    # ---- взаимоисключающие режимы ----
    def test_percent_and_fixed_price_together_is_an_error(self):
        with self.assertRaises(CommandError):
            self._run("--percent", "10", "--fixed-price", "777")
