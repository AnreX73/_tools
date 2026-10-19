"""
shop/migrations/0010_product_price_decimal.py

Цена товара переводится из целых рублей (PositiveIntegerField) в
DecimalField(max_digits=12, decimal_places=2).

* NULL сохраняется как NULL — это «цена по запросу»; такие товары нельзя
  добавить в корзину (проверяется в cart.services).
* Прямое применение: PostgreSQL выполняет ALTER TYPE integer -> numeric(12,2)
  без потерь.
* Откат: перед обратным AlterField копейки округляются до рубля
  (ROUND_HALF_EVEN). Откат необратимо теряет копейки — это ожидаемо,
  старый тип их хранить не умеет.
"""
from decimal import ROUND_HALF_EVEN, Decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models


def round_prices_for_reverse(apps, schema_editor):
    """Округляет цены до рубля перед возвратом к PositiveIntegerField."""
    Product = apps.get_model("shop", "Product")
    queryset = Product.objects.using(schema_editor.connection.alias)
    for pk, price in queryset.exclude(price=None).values_list("pk", "price").iterator():
        rounded = Decimal(price).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
        queryset.filter(pk=pk).update(price=rounded)


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0009_popupnotice"),
    ]

    operations = [
        migrations.AlterField(
            model_name="product",
            name="price",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Обязательна для активного товара",
                max_digits=12,
                null=True,
                validators=[MinValueValidator(Decimal("0"))],
                verbose_name="Цена",
            ),
        ),
        # На откате выполняется раньше обратного AlterField (операции
        # откатываются в обратном порядке).
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=round_prices_for_reverse,
        ),
    ]
