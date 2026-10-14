from django.db import migrations, models
from django.db.models import Q


def hide_unpriced_active_products(apps, schema_editor):
    Product = apps.get_model("shop", "Product")
    Product.objects.filter(is_active=True, price__isnull=True).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0004_remove_product_image_add_productimage"),
    ]

    operations = [
        migrations.RunPython(hide_unpriced_active_products, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="product",
            name="price",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Обязательна для активного товара",
                null=True,
                verbose_name="Цена",
            ),
        ),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.CheckConstraint(
                condition=Q(is_active=False) | Q(price__isnull=False),
                name="active_product_requires_price",
            ),
        ),
    ]
