"""Тесты чтения и регистрации версий юридических документов (ТЗ 3.6)."""

import hashlib
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from avrora_bot.adapters.database.seed import sync_legal_documents
from avrora_bot.adapters.legal.files import (
    FILE_NAMES,
    load_document,
    parse_document,
)
from avrora_bot.domain.enums import LegalDocumentKind
from avrora_bot.domain.errors import ValidationError
from avrora_bot.domain.ports.uow import UnitOfWork

UowFactory = Callable[[], UnitOfWork]

REPO_ROOT = Path(__file__).resolve().parent.parent

_HTML_TEMPLATE = (
    '<html><body><div class="header"><h1>Согласие</h1>'
    '<div class="version">Версия {version} от 14 сентября 2026 г.</div>'
    '</div><p>{body}</p></body></html>'
)


def _write_docs(docs_dir: Path, version: str, body: str = 'текст') -> None:
    docs_dir.mkdir(parents=True, exist_ok=True)
    for name in FILE_NAMES.values():
        (docs_dir / name).write_text(
            _HTML_TEMPLATE.format(version=version, body=body),
            encoding='utf-8',
        )


def test_parse_document_reads_version_date_and_hash() -> None:
    html = _HTML_TEMPLATE.format(version='2.1', body='текст')

    document = parse_document(
        LegalDocumentKind.CONSENT, html, 'https://example.test/consent.html'
    )

    assert document.version == '2.1'
    assert document.effective_date == date(2026, 9, 14)
    assert document.content == html
    assert document.sha256 == hashlib.sha256(html.encode()).hexdigest()
    assert document.url == 'https://example.test/consent.html'


def test_parse_document_without_version_header_fails() -> None:
    with pytest.raises(ValidationError):
        parse_document(LegalDocumentKind.CONSENT, '<html>без версии</html>')


@pytest.mark.parametrize('kind', list(LegalDocumentKind))
def test_published_documents_are_parseable(kind: LegalDocumentKind) -> None:
    # Реальные файлы репозитория: если в заголовке страницы сломается
    # формат «Версия X.Y от ...», бот не сможет зафиксировать согласие.
    document = load_document(kind, REPO_ROOT / 'docs' / 'legal')

    assert document.kind is kind
    assert document.version
    assert document.effective_date is not None


@pytest.mark.asyncio
async def test_sync_registers_each_version_once(
    uow_factory: UowFactory, tmp_path: Path
) -> None:
    docs_dir = tmp_path / 'legal'
    _write_docs(docs_dir, '1.0')

    async with uow_factory() as uow:
        await sync_legal_documents(uow, docs_dir)
        await sync_legal_documents(uow, docs_dir)  # повторный старт бота
        await uow.commit()

    async with uow_factory() as uow:
        versions = await uow.legal_documents.list_for_kind(
            LegalDocumentKind.CONSENT
        )

    assert [d.version for d in versions] == ['1.0']


@pytest.mark.asyncio
async def test_sync_adds_new_version_and_keeps_old_text(
    uow_factory: UowFactory, tmp_path: Path
) -> None:
    docs_dir = tmp_path / 'legal'
    _write_docs(docs_dir, '1.0', body='старый текст')
    async with uow_factory() as uow:
        await sync_legal_documents(uow, docs_dir)
        await uow.commit()

    _write_docs(docs_dir, '1.1', body='новый текст')
    async with uow_factory() as uow:
        await sync_legal_documents(uow, docs_dir)
        await uow.commit()

    async with uow_factory() as uow:
        versions = await uow.legal_documents.list_for_kind(
            LegalDocumentKind.CONSENT
        )

    assert [d.version for d in versions] == ['1.0', '1.1']
    assert 'старый текст' in versions[0].content
    assert 'новый текст' in versions[1].content


@pytest.mark.asyncio
async def test_sync_keeps_stored_text_when_version_not_bumped(
    uow_factory: UowFactory, tmp_path: Path
) -> None:
    # Правка текста без подъёма версии не должна подменять то, с чем уже
    # согласились пользователи: в БД остаётся зафиксированная редакция.
    docs_dir = tmp_path / 'legal'
    _write_docs(docs_dir, '1.0', body='исходный текст')
    async with uow_factory() as uow:
        await sync_legal_documents(uow, docs_dir)
        await uow.commit()

    _write_docs(docs_dir, '1.0', body='правка без новой версии')
    async with uow_factory() as uow:
        await sync_legal_documents(uow, docs_dir)
        await uow.commit()

    async with uow_factory() as uow:
        versions = await uow.legal_documents.list_for_kind(
            LegalDocumentKind.CONSENT
        )

    assert len(versions) == 1
    assert 'исходный текст' in versions[0].content


@pytest.mark.asyncio
async def test_sync_survives_missing_files(
    uow_factory: UowFactory, tmp_path: Path
) -> None:
    # Каталога с документами нет: приложение стартует, но версии не
    # регистрируются — регистрация пользователей будет отклонена.
    async with uow_factory() as uow:
        await sync_legal_documents(uow, tmp_path / 'нет-такого-каталога')
        await uow.commit()
        versions = await uow.legal_documents.list_for_kind(
            LegalDocumentKind.CONSENT
        )

    assert versions == []
