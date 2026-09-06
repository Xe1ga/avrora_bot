#!/usr/bin/env sh
set -e

echo "[entrypoint] Ожидание PostgreSQL ${POSTGRES_HOST}:${POSTGRES_PORT}..."
until python -c "import socket,sys; s=socket.socket(); s.settimeout(2); \
  s.connect(('${POSTGRES_HOST}', int('${POSTGRES_PORT}'))); s.close()" 2>/dev/null; do
  sleep 1
done
echo "[entrypoint] PostgreSQL доступен."

echo "[entrypoint] Применение миграций Alembic..."
alembic upgrade head

echo "[entrypoint] Запуск бота..."
exec python -m avrora_bot
