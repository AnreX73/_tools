# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
"""
shop/management/commands/import_stock.py

Импортирует реальный прайс-остатки клиента (xlsx, 7 листов) в каталог:

    python manage.py import_stock --file /path/to/остатки.xlsx
    python manage.py import_stock --file ... --dry-run        # откатить всё, показать отчёт
    python manage.py import_stock --file ... --flush          # перед импортом удалить все товары
    python manage.py import_stock --file ... --keep-required  # НЕ ослаблять обязательные характеристики

Маппинг листов/заголовков -> категории лежит в shop/data/stock_mapping.json.

Логика по строке файла (колонки: название | ед.изм | количество | сумма):
  * колонка «Сумма» — это суммарная стоимость остатка, цена за единицу = round(сумма/количество);
    если количество пустое — цена = сумма;
  * артикул — префикс названия вида «CK10-58 Набор прижимов...», иначе генерируется GEN-<хэш>;
  * пустая цена, отрицательная сумма/количество, цена 0 -> товар создаётся скрытым (is_active=False)
    и попадает в отчёт для ручной правки;
  * идемпотентность: upsert по sku, повторный запуск обновляет.

В файле нет характеристик, а часть привязок в дереве помечена обязательной —
по умолчанию команда снимает is_required со всех привязок, иначе Product.clean()
отклонит каждый товар. Флаг --keep-required отключает это.
"""
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from openpyxl import load_workbook

from shop.models import Category, CategoryAttribute, Product

DEFAULT_MAPPING = Path(__file__).resolve().parents[2] / "data" / "stock_mapping.json"


class Command(BaseCommand):
    help = "Импорт прайса-остатков (xlsx) в каталог: категории, цены, артикулы"

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Путь к xlsx-файлу остатков")
        parser.add_argument("--mapping", default=str(DEFAULT_MAPPING), help="JSON с маппингом листов/заголовков")
        parser.add_argument("--dry-run", action="store_true", help="Прогон без сохранения (транзакция откатывается)")
        parser.add_argument("--flush", action="store_true", help="Удалить все товары перед импортом")
        parser.add_argument("--keep-required", action="store_true",
                            help="Не снимать is_required с характеристик категорий")

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        xlsx = Path(opts["file"])
        if not xlsx.exists():
            raise CommandError(f"Файл не найден: {xlsx}")
        mapping_path = Path(opts["mapping"])
        if not mapping_path.exists():
            raise CommandError(f"Маппинг не найден: {mapping_path}")
        try:
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise CommandError(f"Некорректный JSON маппинга: {e}") from e

        self.warnings: list[str] = []
        self.hidden_rows: list[tuple] = []
        self.seen_skus: dict[str, str] = {}
        self.stats = {"products": 0, "created": 0, "updated": 0, "hidden": 0, "merged": 0}

        wb = load_workbook(xlsx, read_only=True, data_only=True)
        try:
            with transaction.atomic():
                self._ensure_categories(mapping.get("ensure_categories", []))
                if not opts["keep_required"]:
                    self._relax_required()
                if opts["flush"]:
                    deleted, _ = Product.objects.all().delete()
                    self.stdout.write(self.style.WARNING(f"Товары удалены: {deleted}."))

                sheet_map = {name.strip(): cfg for name, cfg in mapping["sheets"].items()}
                for ws_name in wb.sheetnames:
                    cfg = sheet_map.get(ws_name.strip())
                    if cfg is None:
                        self.warnings.append(f"Лист «{ws_name}» отсутствует в маппинге — пропущен")
                        continue
                    self._import_sheet(wb[ws_name], ws_name, cfg)

                if opts["dry_run"]:
                    transaction.set_rollback(True)
        finally:
            wb.close()

        self._report(opts["dry_run"])

    # ------------------------------------------------------------------
    # Категории
    def _ensure_categories(self, paths):
        for path in paths:
            if self._resolve(path) is None:
                self._create_path(path)
                self.stdout.write(self.style.WARNING(f"Создана категория: {' / '.join(path)}"))

    def _resolve(self, path):
        """Путь-список -> Category или None."""
        parent = None
        for name in path:
            qs = (Category.objects.filter(depth=1, name=name) if parent is None
                  else Category.objects.filter(path__startswith=parent.path,
                                               depth=parent.depth + 1, name=name))
            node = qs.first()
            if node is None:
                return None
            parent = node
        return parent

    def _create_path(self, path):
        parent = None
        for name in path:
            if parent is None:
                qs = Category.objects.filter(depth=1, name=name)
            else:
                qs = Category.objects.filter(path__startswith=parent.path,
                                             depth=parent.depth + 1, name=name)
            node = qs.first()
            if node is None:
                mgr = Category.objects
                if parent is None:
                    node = mgr.add_root(create_kwargs={"name": name}) if hasattr(mgr, "add_root") \
                        else Category.add_root(name=name)
                else:
                    parent.refresh_from_db()
                    node = mgr.add_child(parent, create_kwargs={"name": name}) if hasattr(mgr, "add_child") \
                        else parent.add_child(name=name)
            parent = node

    def _relax_required(self):
        relaxed = CategoryAttribute.objects.filter(is_required=True).update(is_required=False)
        if relaxed:
            self.stdout.write(self.style.WARNING(
                f"Снято is_required с {relaxed} привязок (в файле нет характеристик). "
                "Верните флаги в админке, когда данные будут заполнены."
            ))

    # ------------------------------------------------------------------
    # Разбор листа
    @staticmethod
    def _normalize(text):
        """NBSP -> пробел, схлопывание пробелов, trim."""
        return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()

    def _import_sheet(self, ws, ws_name, cfg):
        # заголовки ищем без учёта «ё/е» — в файле и маппинге написание разнится
        headers_cfg = {k.lower().replace("ё", "е"): v for k, v in cfg.get("headers", {}).items()}
        rules = cfg.get("rules", [])
        default_path = cfg.get("default")

        default_cat = self._resolve(default_path) if default_path else None
        if default_path and default_cat is None:
            self.warnings.append(f"Лист «{ws_name}»: default-категория не найдена: {' / '.join(default_path)}")

        current_cat = None
        count = 0

        for row in ws.iter_rows(min_row=1, max_col=4, values_only=True):
            name, unit, qty, total = row
            if name is None or not str(name).strip():
                continue
            name = self._normalize(str(name))
            has_numbers = any(v is not None and str(v).strip() != "" for v in (unit, qty, total))

            if not has_numbers:
                target = headers_cfg.get(name.lower().replace("ё", "е"))
                if target is not None:
                    # строка-заголовок известного раздела
                    if isinstance(target, dict):  # заголовок с внутренними правилами
                        current_cat = self._resolve(target.get("default", [])) if target.get("default") else None
                        headers_cfg_inner = target
                    else:
                        current_cat = self._resolve(target)
                        headers_cfg_inner = None
                    if current_cat is None:
                        self.warnings.append(f"Лист «{ws_name}»: категория не найдена: {target}")
                    self._current_header_rules = target if isinstance(target, dict) else None
                    continue
                # посторонняя пустая строка — позиция без данных, уходит в скрытые
                cat = current_cat or default_cat
                if cat is None:
                    self.warnings.append(f"Лист «{ws_name}», нет категории: «{name}»")
                    continue
                self._save_product(cat, name, None, None, unit)
                count += 1
                continue

            # обычная товарная строка
            cat = self._by_rules(rules, name)
            if cat is None:
                cat = self._by_header_rules(name)
            if cat is None:
                cat = current_cat or default_cat
            if cat is None:
                self.warnings.append(f"Лист «{ws_name}», нет категории: «{name}»")
                continue
            self._save_product(cat, name, qty, total, unit)
            count += 1

        self._current_header_rules = None
        self.stdout.write(f"Лист «{ws_name}»: {count} товаров")

    def _by_rules(self, rules, name):
        lowered = name.lower()
        for rule in rules:
            if any(kw.lower() in lowered for kw in rule["contains"]):
                cat = self._resolve(rule["category"])
                if cat is None:
                    self.warnings.append(f"Категория правила не найдена: "
                                         f"{' / '.join(rule['category'])} («{name}»)")
                return cat
        return None

    def _by_header_rules(self, name):
        """Внутренние правила текущего заголовка (например «Канавочные резцы»)."""
        target = getattr(self, "_current_header_rules", None)
        if not isinstance(target, dict):
            return None
        return self._by_rules(target.get("rules", []), name)

    # ------------------------------------------------------------------
    # Товар
    def _sku_for(self, name):
        """Артикул из префикса названия или GEN-<хэш>.

        Артикулом считается подряд идущие «артикульные» токены (латиница/цифры),
        например «TL60 M2,2x5,2 Винт прижима» -> sku «TL60 M2,2x5,2».
        Возвращает (sku, name).
        """
        article_re = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-.,+*/_]{1,31}$")
        tokens = name.split()
        article_parts = []
        idx = 0
        for tok in tokens[:3]:
            if article_re.match(tok) and any(ch.isdigit() for ch in tok):
                article_parts.append(tok)
                idx += 1
            else:
                break
        if article_parts:
            sku = " ".join(article_parts)
            rest = " ".join(tokens[idx:]).strip()
            if rest:
                return sku, rest
        digest = hashlib.md5(name.encode("utf-8")).hexdigest()[:8].upper()
        return f"GEN-{digest}", name

    @staticmethod
    def _clean_unit(unit):
        value = str(unit).strip().lower() if unit is not None else ""
        allowed = {c.value for c in Product.Unit}
        return value if value in allowed else Product.Unit.PIECE

    def _save_product(self, category, raw_name, qty, total, unit):
        sku, clean_name = self._sku_for(raw_name)
        clean_name = clean_name or raw_name

        price, issues = None, []
        try:
            qty_f = float(qty) if qty is not None else None
        except (TypeError, ValueError):
            qty_f, _ = None, issues.append("нечисловое количество")
        try:
            total_f = float(total) if total is not None else None
        except (TypeError, ValueError):
            total_f, _ = None, issues.append("нечисловая сумма")

        if total_f is not None and total_f < 0:
            issues.append(f"отрицательная сумма ({total_f:g})")
        if qty_f is not None and qty_f < 0:
            issues.append(f"отрицательное количество ({qty_f:g})")

        if not issues and total_f is not None:
            price = total_f / qty_f if qty_f and qty_f > 0 else total_f
            price = Decimal(str(price)).quantize(Decimal("0.01"))
            if price == 0:
                issues.append(f"нулевая цена (сумма {total_f:g}, кол-во {qty_f})")
        elif total_f is None and not issues:
            issues.append("нет цены")

        is_active = not issues
        if issues:
            self.hidden_rows.append((sku, clean_name, "; ".join(issues)))

        prev = self.seen_skus.get(sku)
        if prev is not None and prev != clean_name:
            # Одинаковый артикул у разных названий — не сливаем, а даём второму свой SKU
            digest = hashlib.md5(f"{sku}|{clean_name}".encode("utf-8")).hexdigest()[:8].upper()
            new_sku = f"GEN-{digest}"
            self.warnings.append(
                f"Артикул «{sku}» уже занят «{prev}» — для «{clean_name}» создан SKU {new_sku}")
            sku = new_sku
            self.stats["merged"] += 1
        self.seen_skus[sku] = clean_name

        product = Product.objects.filter(sku=sku).first()
        created = product is None
        if created:
            product = Product(sku=sku)
        product.name = clean_name[:255]
        product.category = category
        product.unit = self._clean_unit(unit)
        product.price = price
        product.is_active = is_active
        try:
            product.clean()
        except ValidationError as e:
            msg = e.message_dict if hasattr(e, "error_dict") else e.messages
            raise CommandError(f"{sku} «{clean_name}»: {msg}") from e
        product.save()

        self.stats["products"] += 1
        self.stats["created" if created else "updated"] += 1
        if not is_active:
            self.stats["hidden"] += 1

    # ------------------------------------------------------------------
    def _report(self, dry_run):
        s = self.stats
        prefix = "[DRY-RUN] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Готово: товаров {s['products']} (новых {s['created']}, обновлено {s['updated']}, "
            f"скрыто {s['hidden']}, слито дубликатов {s['merged']})."
        ))
        if self.hidden_rows:
            self.stdout.write(self.style.WARNING(f"\nСкрытые позиции ({len(self.hidden_rows)}) — проверьте вручную:"))
            for sku, name, issue in self.hidden_rows:
                self.stdout.write(f"  {sku}: {name[:60]} — {issue}")
        if self.warnings:
            self.stdout.write(self.style.WARNING(f"\nПредупреждения ({len(self.warnings)}):"))
            for w in self.warnings:
                self.stdout.write(f"  {w}")
