# syntax=docker/dockerfile:1

FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# uv — быстрый менеджер зависимостей.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Манифесты и README (нужен для сборки пакета) — слой кэшируется,
# пока не менялись зависимости.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Исходники и конфигурация Alembic.
COPY src ./src
COPY alembic.ini entrypoint.sh ./

# Установка самого пакета (после копирования исходников).
RUN uv sync --frozen --no-dev

RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
