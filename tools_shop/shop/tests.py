"""
Тесты каталога: дерево, характеристики, фильтры и slug.

Запуск (нужен PostgreSQL):
    python manage.py test shop
"""
from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import TestCase

from . import catalog
from .models import Attribute, AttributeOption, Category, CategoryAttribute, Product

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
        product = Product(sku=sku, name=name, category=cls.leaf, attributes=attributes)
        product.full_clean()
        product.save()
        return product

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
        user = get_user_model().objects.create_superuser(username="admin", password="x")
        self.client.force_login(user)
        response = self.client.get(
            "/admin/shop/product/attributes-fields/", {"category": self.leaf.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "attributes__diameter")
        self.assertContains(response, "attributes__tool_material")


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
        cls.drill8 = make("DR-002", "Сверло спиральное Ø8,0 мм", cls.leaf)
        cls.mill = make("ML-100", "Фреза концевая твёрдосплавная", cls.other)
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
