"""
orders/migrations/0002_number_sequences.py

Создаёт последовательности PostgreSQL для номеров заявок и счетов.

Номера не берутся из ``max(number)+1``: последовательность безопасна при
параллельных заявках и не требует блокировки таблицы. Начальные значения
заданы так, чтобы первые номера выглядели как «З-001001» и «С-000001».

Откат удаляет последовательности. Если в базе уже есть заявки/счета, их
номера останутся в строках — при повторном применении нумерация начнётся
с начала и упрётся в unique-ограничение. Это осознанно: откат миграции
на боевой базе с документами требует ручного решения.
"""
from django.db import migrations

ORDER_SEQ = "orders_order_number_seq"
INVOICE_SEQ = "orders_invoice_number_seq"

FORWARD_SQL = f"""
CREATE SEQUENCE IF NOT EXISTS {ORDER_SEQ} START WITH 1001 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS {INVOICE_SEQ} START WITH 1 INCREMENT BY 1;
"""

REVERSE_SQL = f"""
DROP SEQUENCE IF EXISTS {ORDER_SEQ};
DROP SEQUENCE IF EXISTS {INVOICE_SEQ};
"""


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
