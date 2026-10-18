"""
Заменяет одно слово на другое в названиях товаров (Product.name).

Ищется точное вхождение подстроки (регистр учитывается), поэтому
`--find "Fenwerk"` совпадёт только с таким написанием. Пустая строка в
`--replace` означает удаление слова.

После удаления слова в названии остаётся мусор (двойные пробелы, пробел
перед запятой, хвостовые разделители), поэтому результат нормализуется.

Товар пропускается, если его имя не изменилось или после замены стало пустым
(такие товары попадают в отчёт — с ними нужно разобраться руками).

    python manage.py replace_in_names --find "Fenwerk" --replace "" --dry-run
    python manage.py replace_in_names --find "Fenwerk" --replace ""
    python manage.py replace_in_names --find "Fenwerk" --replace "" --rebuild-slugs

По умолчанию slug не трогается (ссылки не ломаются). Флаг --rebuild-slugs
пересобирает slug у изменённых товаров — старые URL перестанут открываться.
"""
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from shop.models import Product

BATCH = 500
SAMPLES = 10


def normalize(name, find, replace):
    """Убирает найденное слово и лишние пробелы/разделители, оставшиеся после него."""
    new = name.replace(find, replace)
    new = re.sub(r"[ \t]+", " ", new)
    new = re.sub(r"\s+([,.;:)])", r"\1", new)
    new = re.sub(r"([(\[])\s+", r"\1", new)
    return new.strip(" \t-–—,;:")


class Command(BaseCommand):
    help = ("Заменяет одно слово на другое в названиях товаров "
            "(--find «слово» --replace «новое», по умолчанию удаление).")

    def add_arguments(self, parser):
        parser.add_argument(
            "--find",
            required=True,
            metavar="СЛОВО",
            help="Что искать в названии товара (точное вхождение, регистр учитывается).",
        )
        parser.add_argument(
            "--replace",
            default="",
            metavar="СЛОВО",
            help="На что заменить. По умолчанию пусто — найденное слово удаляется.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать результат, ничего не записывая в базу.",
        )
        parser.add_argument(
            "--rebuild-slugs",
            action="store_true",
            help="Пересобрать slug изменённых товаров (старые URL перестанут открываться).",
        )

    def handle(self, *args, **options):
        find = options["find"]
        replace = options["replace"]
        if not find:
            raise CommandError("--find не может быть пустым.")
        if find == replace:
            raise CommandError("--find и --replace совпадают — менять нечего.")

        qs = Product.objects.filter(name__contains=find)
        total = qs.count()
        self.stdout.write(
            f"Найдено товаров с «{find}»: {total} (замена на «{replace}»)"
        )
        if not total:
            return

        updates, samples, skipped = [], [], []
        for pk, name in qs.values_list("id", "name").iterator():
            new_name = normalize(name, find, replace)
            if new_name == name:
                continue
            if not new_name:
                skipped.append((pk, name))
                continue
            updates.append((pk, new_name))
            if len(samples) < SAMPLES:
                samples.append(f"  #{pk}: «{name}» -> «{new_name}»")

        self.stdout.write(f"Изменится названий: {len(updates)}")
        if skipped:
            self.stdout.write(f"Пропущено (имя стало бы пустым): {len(skipped)}")
            for pk, name in skipped[:SAMPLES]:
                self.stdout.write(f"  #{pk}: «{name}»")
        if samples:
            self.stdout.write("Примеры:\n" + "\n".join(samples))

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry-run: запись не выполнялась."))
            return
        if not updates:
            self.stdout.write(self.style.WARNING("Менять нечего."))
            return

        now = timezone.now()
        fields = ["name", "updated_at", "slug"] if options["rebuild_slugs"] else ["name", "updated_at"]
        with transaction.atomic():
            for start in range(0, len(updates), BATCH):
                mapping = dict(updates[start:start + BATCH])
                products = list(Product.objects.filter(pk__in=mapping))
                for product in products:
                    product.name = mapping[product.pk]
                    # bulk_update не вызывает auto_now — ставим дату руками.
                    product.updated_at = now
                    if options["rebuild_slugs"]:
                        product.slug = product.build_slug()
                Product.objects.bulk_update(products, fields)

        self.stdout.write(
            self.style.SUCCESS(f"Готово: переименовано товаров — {len(updates)}.")
        )
