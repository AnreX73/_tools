# Команды проекта

Справочник по командам, которые используются в этом проекте: свои management-команды,
служебные команды Django, docker-обвязка и типовые сценарии.

## Как запускать

Команды запускаются из каталога `tools_shop/` (там, где лежит `manage.py`) — в активированном
виртуальном окружении. Виртуальное окружение проекта расположено в корне репозитория, на уровень
выше: `..\.venv`.

```sh
cd tools_shop
..\.venv\Scripts\Activate.ps1        # PowerShell
# либо разово, без активации:
..\.venv\Scripts\python.exe manage.py <команда>
```

Список всех доступных команд (свои помечены секциями `[shop]` и `[chat]`):

```sh
python manage.py help
python manage.py <команда> --help    # флаги конкретной команды
```

> **Windows и кодировка.** Если в консоли вместо текста появляется `UnicodeEncodeError`
> или кракозябры, задайте `$env:PYTHONIOENCODING="utf-8"` перед запуском. Стандартная
> консоль использует cp1251, а в выводе команд есть символы вне её кодировки.

Большинству команд нужны PostgreSQL и Redis — параметры берутся из `.env` (см. последний раздел).

## Сводная таблица

| Команда | Секция | Назначение | Пишет в БД |
|---|---|---|---|
| `seed_shop` | `[shop]` | демо-каталог из `shop/data/seed_shop.json` | да |
| `import_stock` | `[shop]` | реальный прайс-остатки клиента из xlsx | да |
| `raise_prices` | `[shop]` | наценка в процентах или одна цена всем (заглушка) | да |
| `rebuild_slugs` | `[shop]` | пересобрать `slug` категорий и товаров | да |
| `generate_vapid_keys` | `[chat]` | VAPID-пара ключей для `.env` | нет |
| `migrate` | `[django]` | применить миграции | да |
| `collectstatic` | `[staticfiles]` | собрать статику в `staticfiles/` | нет (файлы) |
| `runserver` | `[daphne]` | dev-сервер (Daphne, ASGI → WebSocket работает) | нет |
| `test` | `[django]` | тесты | нет |
| `createsuperuser` | `[auth]` | создать администратора | да |
| `qcluster` | `[django_q]` | воркер очереди задач | да |
| `shell_plus`, `show_urls` | `[django_extensions]` | отладка | нет |

## Свои команды

### `seed_shop` — демо-каталог

Заполняет БД демо-данными из `shop/data/seed_shop.json`: характеристики → дерево категорий
(с привязкой характеристик) → бренды → товары.

```sh
python manage.py seed_shop
python manage.py seed_shop --flush              # сначала вычистить каталог
python manage.py seed_shop --no-products        # только дерево и характеристики
python manage.py seed_shop --file путь\к\другому.json
```

| Флаг | Что делает |
|---|---|
| `--file FILE` | путь к JSON (по умолчанию `shop/data/seed_shop.json`) |
| `--flush` | **удалить ВСЕ товары, категории, характеристики и бренды** перед загрузкой |
| `--no-products` | загрузить только дерево и характеристики |

- Идемпотентна: характеристики ищутся по `code`, варианты по `(характеристика, code)`,
  категории по `(родитель, name)`, товары по `sku`. Повторный запуск ничего не дублирует.
- Каждый товар проходит `Product.clean()` — ту же валидацию, что и форма в админке. Если JSON
  противоречит схеме категории, команда останавливается с понятной ошибкой и откатывает всё
  (одна транзакция).
- Цены товаров берутся из JSON, поэтому `seed_shop` **возвращает исходные цены** даже после
  наценки (см. `raise_prices`).

### `import_stock` — реальный прайс-остатки

Импортирует xlsx-файл остатков клиента (7 листов) в каталог: категории, товары, цены, артикулы.
Маппинг листов и заголовков лежит в `shop/data/stock_mapping.json`.

```sh
python manage.py import_stock --file C:\путь\остатки.xlsx
python manage.py import_stock --file ... --dry-run        # прогон без сохранения
python manage.py import_stock --file ... --flush          # сначала удалить все товары
python manage.py import_stock --file ... --keep-required  # не ослаблять обязательные характеристики
```

| Флаг | Что делает |
|---|---|
| `--file FILE` | путь к xlsx-файлу остатков (**обязателен**) |
| `--mapping FILE` | JSON с маппингом листов/заголовков (по умолчанию `shop/data/stock_mapping.json`) |
| `--dry-run` | прогон без сохранения — транзакция откатывается, печатается отчёт |
| `--flush` | удалить все товары перед импортом |
| `--keep-required` | не снимать `is_required` с обязательных характеристик категорий |

- По строке файла (`название | ед.изм | количество | сумма`) цена за единицу считается как
  `round(сумма / количество)`; если количество пустое — цена равна сумме.
- Артикул — префикс названия (`CK10-58 Набор прижимов…`), иначе генерируется `GEN-<хэш>`.
- Проблемные строки (нет цены, отрицательная сумма/количество, цена 0) → товар создаётся
  **скрытым** (`is_active=False`) и попадает в отчёт для ручной правки.
- Идемпотентна: upsert по `sku`, повторный запуск обновляет товары, а не дублирует.
- В файле нет характеристик, а часть привязок в дереве помечена обязательной. По умолчанию
  команда снимает `is_required` со всех привязок, иначе `Product.clean()` отклонил бы каждый
  товар. Флаг `--keep-required` это поведение отключает.
- **Перезаписывает `price`** у существующих товаров при каждом запуске.

### `raise_prices` — наценка и заглушка цены

Два взаимоисключающих режима: поднять цену на процент или поставить всем товарам одну и ту же цену.

```sh
python manage.py raise_prices --dry-run                    # посмотреть, +15 %
python manage.py raise_prices                              # применить +15 %
python manage.py raise_prices --percent 10                 # применить +10 %
python manage.py raise_prices --fixed-price 1000           # заглушка: только предпросмотр
python manage.py raise_prices --fixed-price 1000 --yes     # заглушка: записать в базу
```

| Флаг | Что делает |
|---|---|
| `--percent N` | поднять цену на N процентов (по умолчанию 15) |
| `--fixed-price РУБ` | заглушка: одна цена всем товарам, у которых уже есть цена |
| `--dry-run` | показать результат, ничего не записывая |
| `--yes` | подтверждение записи для `--fixed-price` (**без него — только предпросмотр**) |

- `--percent` и `--fixed-price` взаимоисключающие: указать оба нельзя, команда выдаст ошибку.
- Охват в обоих режимах одинаковый — только товары с ценой > 0. Товары с «ценой по запросу»
  (`price IS NULL`) и с ценой 0 не трогаются.
- Округление до рубля — `ROUND_HALF_EVEN`, то есть ровно то же, что делает `round()`
  при импорте. Пример: 4098 ₽ → 4713 ₽.
- `updated_at` проставляется у изменённых товаров; уже совпадающие цены не перезаписываются.
- **Не идемпотентна:** каждый запуск без `--dry-run` накидывает процент ещё раз (цены уходят
  вверх на 15 % от новых). Всегда сначала `--dry-run`.
- После наценки повторный `--dry-run` **снова покажет изменения**: процент считается от новых
  цен, и это нормальное поведение команды, а не признак ошибки. «Изменится цен: 0» вы увидите
  только у `--fixed-price`, если цены уже равны заданной.

### `rebuild_slugs` — пересборка ЧПУ

Пересобирает `slug` категорий и товаров по правилу `make_slug(name)-<id>`.

```sh
python manage.py rebuild_slugs
```

Флагов нет. Нужна один раз после правки правил генерации `slug` (например, когда из названий
убрали не-ASCII символы вроде `Ø`), потому что `slug` не пересчитывается автоматически и не
меняется при переименовании объекта.

### `generate_vapid_keys` — ключи Web Push

Генерирует пару VAPID-ключей и печатает её в формате переменных `.env`.

```sh
python manage.py generate_vapid_keys
```

- Ничего в БД и настройках не меняет — только печатает ключи.
- Запускается один раз: значения `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` копируются в `.env`
  и переиспользуются во всех развёртываниях. Приватный ключ хранится в секрете.

## Служебные команды Django

| Команда | Пример | Комментарий |
|---|---|---|
| `migrate` | `python manage.py migrate` | применить миграции |
| `collectstatic` | `python manage.py collectstatic --noinput` | собрать статику в `staticfiles/` |
| `runserver` | `python manage.py runserver` | переопределён Daphne, поэтому WebSocket чата работает |
| `test` | `python manage.py test` | все тесты, сейчас 63 |
| `test` (один класс) | `python manage.py test shop.tests.RaisePricesCommandTestCase` | быстрее при отладке |
| `createsuperuser` | `python manage.py createsuperuser` | администратор для `/admin/` |
| `qcluster` | `python manage.py qcluster` | воркер django-q (нужен Redis) |

Отладочные команды из `django_extensions`, которые чаще всего нужны:

```sh
python manage.py shell_plus          # shell с автоподключением моделей
python manage.py show_urls           # список всех URL
python manage.py print_settings      # печать текущих настроек
```

Ещё в проекте есть `[django_q]`: `qinfo`, `qmonitor`, `qmemory` — состояние очереди задач.

## Docker

Прод-раскладка — файл `compose.yml`. Сервисы: `db` (postgres:17-alpine), `redis` (redis:7-alpine),
`web` (Daphne на порту 8000 внутри контейнера), `qcluster` (воркер задач), `nginx` (отдаёт
статику и медиа, проксирует на `web:8000`).

```sh
cd tools_shop
docker compose up -d --build          # собрать и поднять
docker compose ps                     # статус
docker compose logs -f web            # логи
docker compose down                   # остановить
```

Команды выполняются **внутри контейнера** `web` — он ходит в тот же PostgreSQL, что и сайт.
Файлы для импорта сначала копируются в контейнер:

```sh
docker compose cp C:\путь\остатки.xlsx web:/app/остатки.xlsx
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_shop
docker compose exec web python manage.py import_stock --file /app/остатки.xlsx
docker compose exec web python manage.py createsuperuser
```

Важные детали:

- `docker-entrypoint.sh` выполняет `migrate` и `collectstatic` только когда `RUN_MIGRATIONS=1`
  — флаг стоит у сервиса `web`, чтобы `qcluster` не запускал их параллельно.
- `nginx` не публикует порт наружу: трафик идёт через Nginx Proxy Manager (внешняя сеть
  `npm_default`). Имя сети при необходимости меняется в `compose.yml`.
- Данные PostgreSQL лежат в томе `pg_data`, медиа — в `media_data`.
- Для локальной разработки без Docker в `.env` используются `DB_HOST=localhost` и
  `DB_PORT=5433`; внутри compose они переопределяются на `db:5432` через переменные сервиса.

## Типовые сценарии

**Первый запуск локально**

```sh
cd tools_shop
..\.venv\Scripts\Activate.ps1
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_shop          # если нужен демо-каталог
python manage.py runserver
```

**Загрузить реальный прайс клиента**

```sh
python manage.py import_stock --file C:\путь\остатки.xlsx --dry-run   # проверить отчёт
python manage.py import_stock --file C:\путь\остатки.xlsx
```

**Поднять цены на 15 %**

```sh
python manage.py raise_prices --dry-run     # посмотреть примеры и количество
python manage.py raise_prices               # применить
```

**Поставить всем товарам одинаковую цену (заглушка)**

```sh
python manage.py raise_prices --fixed-price 1000          # предпросмотр
python manage.py raise_prices --fixed-price 1000 --yes    # записать
```

**Прогнать тесты перед коммитом**

```sh
python manage.py test
python -m ruff check .
```

## Опасные команды и бэкап

Правило: перед любой массовой правкой данных сначала `--dry-run` (если он есть), затем бэкап.

| Команда | Чем опасна |
|---|---|
| `seed_shop --flush` | удаляет все товары, категории, характеристики и бренды |
| `import_stock --flush` | удаляет все товары перед импортом |
| `import_stock` | пересчитывает и перезаписывает `price` у существующих товаров |
| `raise_prices` | не идемпотентна — повторный запуск накидывает процент ещё раз |
| `raise_prices --fixed-price` | перезаписывает весь прайс одной цифрой (защита — флаг `--yes`) |

**Бэкап цен.** На хосте утилит `pg_dump`/`psql` нет, поэтому доступны три способа:

1. Выгрузка модели в JSON (восстанавливается через `loaddata`):

   ```sh
   python manage.py dumpdata shop.Product --indent 2 -o products_backup.json
   python manage.py loaddata products_backup.json
   ```

2. Быстрый CSV `id, price` — удобно глазами проверить и точечно откатить:

   ```sh
   python manage.py shell_plus
   ```

   ```python
   import csv
   from shop.models import Product
   with open("prices_backup.csv", "w", newline="", encoding="utf-8") as f:
       w = csv.writer(f)
       w.writerow(["id", "price"])
       w.writerows(Product.objects.values_list("id", "price"))
   ```

   Откат из этого файла:

   ```python
   import csv
   from django.db import transaction
   from shop.models import Product
   with open("prices_backup.csv", encoding="utf-8") as f:
       rows = list(csv.DictReader(f))
   with transaction.atomic():
       for row in rows:
           price = None if row["price"] == "" else int(row["price"])
           Product.objects.filter(pk=row["id"]).update(price=price)
   ```

3. Полный дамп базы средствами контейнера:

   ```sh
   docker compose exec db pg_dump -U <DB_USER> -d <DB_NAME> -f /tmp/backup.sql
   docker compose cp db:/tmp/backup.sql .\backup.sql
   ```

   Значения `<DB_USER>` и `<DB_NAME>` подставьте из `.env`.

## Конвенции цен

- Цена товара — целое число рублей (`PositiveIntegerField`). НДС и скидки считаются при выводе
  или в заказе.
- `price IS NULL` означает «цена по запросу» — так помечены товары, у которых цены нет.
- У активного товара цена обязательна (ограничение БД `active_product_requires_price`),
  у скрытого может быть пустой.
- Округление при расчётах — до рубля, `ROUND_HALF_EVEN` (как `round()` в Python), это
  используется и в `import_stock`, и в `raise_prices`.

## Переменные окружения

Команды читают настройки из `tools_shop/.env`. Ключевое:

| Переменная | Назначение |
|---|---|
| `SECRET_KEY` | ключ Django |
| `DEBUG` | режим отладки |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | подключение к PostgreSQL |
| `REDIS_HOST`, `REDIS_PORT` | Redis (кэш, django-q, WebSocket-канал) |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | домены сайта |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | Web Push (см. `generate_vapid_keys`) |

Файл `.env` в git не попадает. При первом клоне репозитория его нужно создать вручную по этой
таблице: без него не запустится ни Django, ни `docker compose` (он подключает `.env` через
`env_file`).

## См. также

- `chat/README.md` — чат с посетителями и Web Push.
- `chat/PWA.md` — PWA-обвязка.
- `../project_stages.md` — конспект по проекту: модели, витрина, Docker, поиск.
- `../AGENT.md` — правила работы ассистента в этом репозитории.
