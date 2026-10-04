#!/bin/sh
set -e

# Миграции и статика выполняются только в web-контейнере (RUN_MIGRATIONS=1),
# чтобы qcluster не гонял их параллельно.
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput
fi

exec "$@"
