"""Чтение версий юридических документов из ``docs/legal/*.html``.

Источник истины — сами HTML-файлы репозитория: версия и дата берутся из
заголовка страницы («Версия 1.0 от 14 сентября 2026 г.»), а содержимое
целиком и его sha256 сохраняются в БД при старте приложения
(``adapters.database.seed.sync_legal_documents``). Поэтому для публикации
новой редакции достаточно поправить текст файла и поднять номер версии в
заголовке — отдельная настройка версии в окружении не нужна.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

from avrora_bot.domain.entities import LegalDocument
from avrora_bot.domain.enums import LegalDocumentKind
from avrora_bot.domain.errors import ValidationError

# Имена файлов документов внутри каталога docs/legal/.
FILE_NAMES: dict[LegalDocumentKind, str] = {
    LegalDocumentKind.CONSENT: 'consent.html',
    LegalDocumentKind.PRIVACY_POLICY: 'privacy-policy.html',
}

# Заголовок версии на странице: <div class="version">Версия 1.0 от 14
# сентября 2026 г.</div>. Дата необязательна — без неё фиксируется только
# номер версии.
_VERSION_RE = re.compile(
    r'class="version"[^>]*>\s*Версия\s+(?P<version>[0-9A-Za-z.\-_]+)'
    r'(?:\s*от\s+(?P<day>\d{1,2})\s+(?P<month>[А-Яа-яЁё]+)\s+(?P<year>\d{4}))?',
)

_MONTHS: dict[str, int] = {
    'января': 1,
    'февраля': 2,
    'марта': 3,
    'апреля': 4,
    'мая': 5,
    'июня': 6,
    'июля': 7,
    'августа': 8,
    'сентября': 9,
    'октября': 10,
    'ноября': 11,
    'декабря': 12,
}


def _parse_effective_date(match: re.Match[str]) -> date | None:
    """Собирает дату вступления в силу из групп регулярного выражения."""
    month_name = match.group('month')
    if month_name is None:
        return None
    month = _MONTHS.get(month_name.lower())
    if month is None:
        return None
    return date(int(match.group('year')), month, int(match.group('day')))


def parse_document(
    kind: LegalDocumentKind, html: str, url: str | None = None
) -> LegalDocument:
    """Разбирает HTML документа в доменную сущность ``LegalDocument``.

    :raises ValidationError: если в тексте нет заголовка с номером версии.
    """
    match = _VERSION_RE.search(html)
    if match is None:
        raise ValidationError(
            f'В документе «{kind.value}» не найден заголовок '
            'вида «Версия X.Y от ДД месяца ГГГГ г.»'
        )
    return LegalDocument(
        kind=kind,
        version=match.group('version'),
        sha256=hashlib.sha256(html.encode('utf-8')).hexdigest(),
        content=html,
        effective_date=_parse_effective_date(match),
        url=url,
    )


def load_document(
    kind: LegalDocumentKind, docs_dir: Path, url: str | None = None
) -> LegalDocument:
    """Читает файл документа из каталога и разбирает его версию.

    :raises FileNotFoundError: если файла нет в ``docs_dir``.
    :raises ValidationError: если в файле нет заголовка с версией.
    """
    path = docs_dir / FILE_NAMES[kind]
    return parse_document(kind, path.read_text(encoding='utf-8'), url)
