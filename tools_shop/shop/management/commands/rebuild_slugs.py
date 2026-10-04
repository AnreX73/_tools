"""
Пересобирает slug у категорий и товаров: slug = make_slug(name) + "-" + id.

Нужен один раз после правки правил slug-генерации (например, когда из названий
убрали не-ASCII символы вроде «Ø»), потому что slug не меняется автоматически.

    python manage.py rebuild_slugs
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from shop.models import Category, Product


class Command(BaseCommand):
    help = "Пересобирает slug категорий и товаров (slug = make_slug(name)-<id>)."

    def handle(self, *args, **options):
        with transaction.atomic():
            for label, model in (("категорий", Category), ("товаров", Product)):
                changed = 0
                for obj in model.objects.all().iterator():
                    new_slug = obj.build_slug()
                    if obj.slug != new_slug:
                        # новый slug всегда уникален: суффикс — собственный pk
                        model._default_manager.filter(pk=obj.pk).update(slug=new_slug)
                        changed += 1
                self.stdout.write(f"Обновлено {label}: {changed}")
        self.stdout.write(self.style.SUCCESS("Готово."))
