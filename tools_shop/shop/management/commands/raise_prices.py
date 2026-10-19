"""
Меняет цены товаров в базе. Два режима (взаимоисключающие):

  * --percent N   — поднять цену на N процентов (по умолчанию +15 %);
  * --fixed-price — заглушка: поставить всем товарам одну и ту же цену.
                    Пишет в базу только с подтверждением --yes.

Цена хранится как Decimal(12,2), поэтому процент считается точно и
округляется до копейки (ROUND_HALF_EVEN).

Товары с пустой ценой («цена по запросу», price IS NULL) и с ценой 0
не трогаются в обоих режимах: у первых цены нет, у вторых менять нечего.

    python manage.py raise_prices --dry-run                     # показать, +15 %
    python manage.py raise_prices                               # +15 %
    python manage.py raise_prices --percent 10                  # +10 %
    python manage.py raise_prices --fixed-price 1000            # предпросмотр заглушки
    python manage.py raise_prices --fixed-price 1000 --yes      # записать заглушку

Команда НЕ идемпотентна: каждый запуск без --dry-run применяет процент ещё
раз (цены уходят вверх). Поэтому сначала --dry-run и оценка результата.
"""
from decimal import ROUND_HALF_EVEN, Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from shop.models import Product

BATCH = 500
SAMPLES = 10
CENT = Decimal("0.01")


def _raised(price, factor):
    """Цена +процент, округлённая до копейки."""
    return (Decimal(price) * factor).quantize(CENT, rounding=ROUND_HALF_EVEN)


class Command(BaseCommand):
    help = ("Меняет цены товаров: --percent (по умолчанию +15 %) "
            "или --fixed-price (заглушка: одна цена всем, требует --yes).")

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--percent",
            type=Decimal,
            default=Decimal("15"),
            metavar="N",
            help="На сколько процентов поднять цену (по умолчанию 15).",
        )
        mode.add_argument(
            "--fixed-price",
            type=Decimal,
            metavar="ЦЕНА",
            help="Заглушка: поставить всем товарам с ценой одну и ту же цену. "
                 "Без --yes выполняется только предпросмотр.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать результат, ничего не записывая в базу.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Подтвердить запись для --fixed-price (перезаписывает прайс целиком).",
        )

    def handle(self, *args, **options):
        fixed_price = options["fixed_price"]
        percent = options["percent"]

        # price IS NULL — «цена по запросу», price = 0 — менять нечего.
        qs = Product.objects.filter(price__gt=0).only("id", "price")
        total = qs.count()

        if fixed_price is None:
            factor = Decimal(1) + percent / Decimal(100)
            self.stdout.write(f"Режим: +{percent} % (множитель x{factor})")

            def new_price_for(price):
                return _raised(price, factor)
        else:
            if fixed_price < 0:
                raise CommandError("Цена не может быть отрицательной.")
            self.stdout.write(
                f"Режим-заглушка: одна цена {fixed_price} руб. для всех товаров с ценой"
            )

            def new_price_for(price):  # noqa: ARG001 — цена-заглушка от исходной не зависит
                return fixed_price

        updates, samples = [], []
        for pk, price in qs.values_list("id", "price").iterator():
            new_price = new_price_for(price)
            if new_price == price:
                continue
            updates.append((pk, new_price))
            if len(samples) < SAMPLES:
                samples.append(f"  #{pk}: {price} -> {new_price}")

        self.stdout.write(f"Товаров с ценой > 0: {total}; изменится цен: {len(updates)}")
        if samples:
            self.stdout.write("Примеры:\n" + "\n".join(samples))

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry-run: запись не выполнялась."))
            return

        if fixed_price is not None and not options["yes"]:
            self.stdout.write(self.style.WARNING(
                "Заглушка перезаписывает прайс целиком — подтвердите запуск флагом --yes."))
            return

        now = timezone.now()
        with transaction.atomic():
            for start in range(0, len(updates), BATCH):
                mapping = dict(updates[start:start + BATCH])
                products = list(Product.objects.filter(pk__in=mapping))
                for product in products:
                    product.price = mapping[product.pk]
                    # bulk_update не вызывает auto_now — ставим дату руками.
                    product.updated_at = now
                Product.objects.bulk_update(products, ["price", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(f"Готово: обновлено цен у {len(updates)} товаров.")
        )
