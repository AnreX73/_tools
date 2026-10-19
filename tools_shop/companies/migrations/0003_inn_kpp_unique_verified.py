"""
companies/migrations/0003_inn_kpp_unique_verified.py

Что делает миграция
-------------------
1. Нормализует существующие ИНН/КПП: обрезает пробелы, пустой КПП приводит
   к пустой строке (у ИП КПП нет).
2. Проверяет, что после нормализации не появилось дублей пары (ИНН, КПП).
   Если дубли есть — миграция падает с явным списком pk и значений.
   Молча «схлопывать» организации нельзя: это разные юрлица/подразделения.
3. Снимает unique с ИНН, добавляет обычный индекс и валидатор контрольной
   суммы, добавляет is_verified / confirmed_at и UniqueConstraint(inn, kpp).
4. Помечает все уже существующие компании как проверенные менеджером:
   они заведены вручную до появления флага.

Про данные, которые НЕ ломают миграцию
--------------------------------------
* ИНН с неверной контрольной суммой — выводится предупреждение со списком pk,
  строка сохраняется (иначе миграцию нельзя применить на боевой базе, а
  исправлять реквизиты должен менеджер, а не DBA).
* 10-значный ИНН без КПП — тоже только предупреждение: clean() начнёт
  требовать КПП для новых/редактируемых записей, но старые не блокируем.

Обратимость
-----------
Reverse повторяет операции в обратном порядке. AlterField(inn, unique=True)
упадёт, если к моменту отката появятся две компании с одинаковым ИНН (это
стало допустимым после прямого применения). Это осознанное поведение:
данные не теряются, конфликт нужно разрешить вручную. Остальные операции
(is_verified, confirmed_at, constraint) откатываются чисто.
"""
from django.db import migrations, models

import companies.validators


def normalize_and_check(apps, schema_editor):
    LegalEntity = apps.get_model("companies", "LegalEntity")
    db_alias = schema_editor.connection.alias
    queryset = LegalEntity.objects.using(db_alias)

    # --- нормализация ---
    for entity in queryset.only("pk", "inn", "kpp").iterator():
        inn = (entity.inn or "").strip()
        kpp = (entity.kpp or "").strip()
        if inn != entity.inn or kpp != entity.kpp:
            queryset.filter(pk=entity.pk).update(inn=inn, kpp=kpp)

    # --- дубли пары (ИНН, КПП) ---
    duplicates = (
        queryset.values("inn", "kpp")
        .annotate(total=models.Count("pk"))
        .filter(total__gt=1)
        .order_by("inn", "kpp")
    )
    if duplicates:
        lines = []
        for row in duplicates:
            pks = list(
                queryset.filter(inn=row["inn"], kpp=row["kpp"])
                .order_by("pk")
                .values_list("pk", flat=True)
            )
            lines.append(f"  ИНН={row['inn']!r}, КПП={row['kpp']!r}: pk={pks}")
        raise RuntimeError(
            "Миграция companies.0003 остановлена: после нормализации найдены "
            "дубли пары (ИНН, КПП). Объедините или исправьте организации "
            "вручную, затем повторите migrate.\n" + "\n".join(lines)
        )

    # --- предупреждения, не блокирующие миграцию ---
    invalid_inn, missing_kpp = [], []
    for pk, inn, kpp in queryset.values_list("pk", "inn", "kpp").iterator():
        if not companies.validators.is_valid_inn(inn or ""):
            invalid_inn.append(pk)
        elif len(inn) == 10 and not kpp:
            missing_kpp.append(pk)
    if invalid_inn:
        print(
            "\n  ВНИМАНИЕ: ИНН с неверной контрольной суммой у компаний "
            f"pk={invalid_inn}. Записи сохранены, реквизиты нужно проверить.\n"
        )
    if missing_kpp:
        print(
            "\n  ВНИМАНИЕ: у компаний с 10-значным ИНН не заполнен КПП: "
            f"pk={missing_kpp}. Новые записи без КПП будут отклоняться.\n"
        )


def mark_existing_verified(apps, schema_editor):
    """Все компании, заведённые до появления флага, считаем проверенными."""
    LegalEntity = apps.get_model("companies", "LegalEntity")
    LegalEntity.objects.using(schema_editor.connection.alias).update(is_verified=True)


class Migration(migrations.Migration):

    dependencies = [
        ("companies", "0002_remove_legalentity_company_inn_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(normalize_and_check, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="legalentity",
            name="inn",
            field=models.CharField(
                db_index=True,
                help_text="10 цифр (юрлицо) или 12 цифр (ИП)",
                max_length=12,
                validators=[companies.validators.validate_inn],
                verbose_name="ИНН",
            ),
        ),
        migrations.AddField(
            model_name="legalentity",
            name="is_verified",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Реквизиты сверены менеджером; непроверенные компании "
                    "не участвуют в автоматических сценариях."
                ),
                verbose_name="Проверена менеджером",
            ),
        ),
        migrations.AddField(
            model_name="companyuser",
            name="confirmed_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Когда пользователь подтвердил связь с компанией.",
                null=True,
                verbose_name="Подтверждён",
            ),
        ),
        migrations.RunPython(mark_existing_verified, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="legalentity",
            constraint=models.UniqueConstraint(
                fields=("inn", "kpp"), name="uniq_inn_kpp"
            ),
        ),
    ]
