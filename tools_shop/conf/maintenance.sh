#!/usr/bin/env bash
# Переключение сайта между рабочим режимом и заглушкой «Технические работы».
#
# Использование (из корня проекта или из любой папки):
#   bash conf/maintenance.sh on       # включить заглушку
#   bash conf/maintenance.sh off      # вернуть сайт
#   bash conf/maintenance.sh status   # показать текущий режим
#
# Как это работает: контейнер nginx монтирует conf/nginx.conf. Скрипт копирует в
# него один из шаблонов — nginx.maintenance.conf или nginx.working.conf. Сам
# nginx.conf в git не хранится (см. .gitignore), поэтому git pull не сбрасывает
# выбранный на сервере режим.
set -euo pipefail

CONF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$CONF_DIR")"
NGINX_CONF="$CONF_DIR/nginx.conf"
WORKING_CONF="$CONF_DIR/nginx.working.conf"
MAINTENANCE_CONF="$CONF_DIR/nginx.maintenance.conf"
NGINX_SERVICE="nginx"

usage() {
  cat <<'EOF'
Использование: bash conf/maintenance.sh <команда>

Команды:
  on      включить заглушку «Технические работы»
  off     выключить заглушку, вернуть сайт
  status  показать текущий режим
EOF
}

die() {
  echo "Ошибка: $*" >&2
  exit 1
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    die "Docker Compose не найден (нужен 'docker compose' или 'docker-compose')."
  fi
}

# Если conf/nginx.conf пропал (например, его удалил git pull после снятия файла
# с учёта в git), восстанавливаем рабочую версию, чтобы nginx не остался без
# конфига и сайт не упал.
ensure_nginx_conf() {
  if [ -d "$NGINX_CONF" ]; then
    # Если файла не было в момент старта контейнера, Docker создаёт на его месте
    # пустой каталог. Убираем его, иначе на место файла конфиг уже не положить.
    if rmdir "$NGINX_CONF" 2>/dev/null; then
      echo "conf/nginx.conf был пустым каталогом (артефакт Docker) — удалён." >&2
    else
      die "$NGINX_CONF — каталог, а не файл. Удалите его вручную: rm -rf '$NGINX_CONF'"
    fi
  fi
  if [ ! -f "$NGINX_CONF" ]; then
    cp "$WORKING_CONF" "$NGINX_CONF"
    echo "conf/nginx.conf отсутствовал — восстановлен из nginx.working.conf." >&2
  fi
}

nginx_container_id() {
  (cd "$PROJECT_DIR" && compose ps -q "$NGINX_SERVICE" 2>/dev/null || true) | head -n 1
}

nginx_running() {
  local cid
  cid="$(nginx_container_id)"
  [ -n "$cid" ] || return 1
  [ "$(docker inspect -f '{{.State.Running}}' "$cid" 2>/dev/null || echo false)" = "true" ]
}

restart_nginx() {
  echo "Перезапускаю контейнер nginx..."
  # up -d --no-deps применяет изменения compose (например, новый volume для
  # maintenance.html), но НЕ поднимает зависимости (web, db) — это важно, если
  # приложение остановлено на время работ. Если применить не удалось (нет
  # внешней сети, образ не собран), всё равно пробуем обычный restart.
  (cd "$PROJECT_DIR" && compose up -d --no-deps "$NGINX_SERVICE" >/dev/null) \
    || echo "Предупреждение: не удалось применить настройки compose, перезапускаю как есть." >&2
  (cd "$PROJECT_DIR" && compose restart "$NGINX_SERVICE" >/dev/null)
}

apply_template() {
  local src="$1" previous=""
  [ -f "$src" ] || die "не найден шаблон $src"

  if [ -f "$NGINX_CONF" ] && ! cmp -s "$NGINX_CONF" "$src"; then
    previous="$CONF_DIR/.nginx.conf.previous"
    cp "$NGINX_CONF" "$previous"
  fi
  cp "$src" "$NGINX_CONF"

  # conf/nginx.conf смонтирован в контейнер, поэтому новый конфиг можно проверить
  # ещё до перезапуска. Если nginx его не принимает — откатываемся и выходим.
  if nginx_running && ! (cd "$PROJECT_DIR" && compose exec -T "$NGINX_SERVICE" nginx -t >/dev/null 2>&1); then
    if [ -n "$previous" ]; then
      cp "$previous" "$NGINX_CONF"
    else
      cp "$WORKING_CONF" "$NGINX_CONF"
    fi
    rm -f "$previous"
    die "nginx не принял новый конфиг, прежний конфиг восстановлен. Детали: docker compose exec nginx nginx -t"
  fi
  rm -f "$previous"

  restart_nginx
}

[ -f "$WORKING_CONF" ] || die "не найден $WORKING_CONF"
[ -f "$MAINTENANCE_CONF" ] || die "не найден $MAINTENANCE_CONF"

case "${1:-}" in
  on)
    ensure_nginx_conf
    apply_template "$MAINTENANCE_CONF"
    echo "Готово: заглушка включена, посетители видят «Технические работы»."
    ;;
  off)
    ensure_nginx_conf
    apply_template "$WORKING_CONF"
    echo "Готово: заглушка выключена, сайт снова работает."
    ;;
  status)
    ensure_nginx_conf
    if cmp -s "$NGINX_CONF" "$MAINTENANCE_CONF"; then
      echo "Текущий режим: заглушка включена."
    elif cmp -s "$NGINX_CONF" "$WORKING_CONF"; then
      echo "Текущий режим: сайт работает."
    else
      echo "Текущий режим: неизвестно — conf/nginx.conf отличается от обоих шаблонов." >&2
      exit 1
    fi
    if nginx_running; then
      echo "Контейнер nginx: запущен."
    else
      echo "Контейнер nginx: не запущен."
    fi
    ;;
  *)
    usage
    exit 1
    ;;
esac
