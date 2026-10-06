#!/usr/bin/env bash
# Проверка качества (quality gate) — единая для разработчика и агентов.
#
#   scripts/check.sh                      # всё: линтер, формат изменённых файлов,
#                                         # все тесты, миграции (если менялись)
#   scripts/check.sh tests/test_x.py ...  # то же, но тесты — только указанные
#   scripts/check.sh --no-tests           # без тестов
#
# Код возврата: 0 — все проверки пройдены, иначе 1. В конце — сводка.
set -uo pipefail
cd "$(dirname "$0")/.."

# В песочнице на WSL-маунте .venv/bin/python не запускается — тогда берём
# системный python3 и пакеты из .venv через PYTHONPATH.
if .venv/bin/python -c '' 2>/dev/null; then
    PY=(.venv/bin/python)
else
    export PYTHONPATH=".venv/lib/python3.14/site-packages:src${PYTHONPATH:+:$PYTHONPATH}"
    PY=(python3)
fi

RUN_TESTS=1
PYTEST_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --no-tests) RUN_TESTS=0 ;;
        *) PYTEST_ARGS+=("$arg") ;;
    esac
done

FAILED=()
step() {
    local name=$1
    shift
    echo "▶ $name"
    if "$@"; then
        echo "✔ $name"
    else
        echo "✘ $name"
        FAILED+=("$name")
    fi
}

# Изменённые и новые файлы относительно HEAD (режимы файлов на маунте
# «меняются» сами — игнорируем).
mapfile -t CHANGED < <(
    {
        git -c core.fileMode=false diff --name-only HEAD
        git ls-files --others --exclude-standard
    } | sort -u
)
CHANGED_PY=()
MIGRATIONS_CHANGED=0
for f in "${CHANGED[@]}"; do
    [[ -f "$f" && "$f" == *.py ]] && CHANGED_PY+=("$f")
    [[ "$f" == *alembic/migrations/* ]] && MIGRATIONS_CHANGED=1
done

step 'ruff check' "${PY[@]}" -m ruff check src tests scripts

# Формат проверяем только у изменённых файлов: часть старого кода
# отформатирована вручную, массовое переформатирование — отдельная задача.
if ((${#CHANGED_PY[@]})); then
    step 'ruff format (изменённые файлы)' \
        "${PY[@]}" -m ruff format --check "${CHANGED_PY[@]}"
fi

check_migrations() {
    local db
    db=$(mktemp "${TMPDIR:-/tmp}/avrora_check_XXXXXX.db")
    rm -f "$db"
    export ALEMBIC_DSN="sqlite+aiosqlite:///$db"
    "${PY[@]}" -m alembic upgrade head \
        && "${PY[@]}" -m alembic check \
        && "${PY[@]}" -m alembic downgrade -1 \
        && "${PY[@]}" -m alembic upgrade head
    local rc=$?
    rm -f "$db"
    return $rc
}
if ((MIGRATIONS_CHANGED)); then
    step 'alembic upgrade/check/downgrade' check_migrations
fi

if ((RUN_TESTS)); then
    step 'pytest' "${PY[@]}" -m pytest -q -p no:cacheprovider "${PYTEST_ARGS[@]}"
fi

echo
if ((${#FAILED[@]})); then
    echo "ИТОГ: провалено — ${FAILED[*]}"
    exit 1
fi
echo 'ИТОГ: все проверки пройдены'
