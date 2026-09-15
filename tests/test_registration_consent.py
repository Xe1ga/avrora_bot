"""Тесты фиксации согласия на обработку персональных данных (ТЗ 3.6, 152-ФЗ)."""

from collections.abc import Callable
from datetime import date

import pytest

from avrora_bot.application.use_cases.legal import LegalUseCases
from avrora_bot.application.use_cases.registration import (
    RegistrationData,
    RegistrationUseCases,
)
from avrora_bot.domain import entities as e
from avrora_bot.domain.enums import LegalDocumentKind
from avrora_bot.domain.errors import NotFoundError
from avrora_bot.domain.ports.uow import UnitOfWork
from tests.conftest import FakeVkGateway

PLAYER_VK_ID = 101

UowFactory = Callable[[], UnitOfWork]


def _document(kind: LegalDocumentKind, version: str = '1.0') -> e.LegalDocument:
    return e.LegalDocument(
        kind=kind,
        version=version,
        sha256=f'{kind.value}-{version}-hash',
        content=f'<html>{kind.value} {version}</html>',
        effective_date=date(2026, 9, 14),
        url=f'https://example.test/{kind.value}.html',
    )


async def _publish_documents(
    uow_factory: UowFactory, version: str = '1.0'
) -> tuple[e.LegalDocument, e.LegalDocument]:
    """Регистрирует по одной версии обоих документов."""
    async with uow_factory() as uow:
        consent = await uow.legal_documents.add(
            _document(LegalDocumentKind.CONSENT, version)
        )
        privacy = await uow.legal_documents.add(
            _document(LegalDocumentKind.PRIVACY_POLICY, version)
        )
        await uow.commit()
    return consent, privacy


@pytest.mark.asyncio
async def test_self_register_records_consent(
    uow_factory: UowFactory,
) -> None:
    consent_doc, privacy_doc = await _publish_documents(uow_factory)
    reg = RegistrationUseCases(uow_factory, FakeVkGateway())

    user = await reg.self_register(
        RegistrationData(
            vk_id=PLAYER_VK_ID,
            full_name='Иван Иванов',
            birthdate=date(2000, 1, 1),
            height_cm=180,
            phone='+70000000000',
            consent_document_id=consent_doc.id,
            privacy_policy_document_id=privacy_doc.id,
        )
    )

    async with uow_factory() as uow:
        records = await uow.consents.list_for_user(user.id)

    assert len(records) == 1
    assert records[0].user_id == user.id
    assert records[0].consent_document_id == consent_doc.id
    assert records[0].privacy_policy_document_id == privacy_doc.id
    assert records[0].given_at is not None


@pytest.mark.asyncio
async def test_consent_keeps_text_of_accepted_version(
    uow_factory: UowFactory,
) -> None:
    # Ради этого и заведена таблица версий: после публикации новой редакции
    # согласие пользователя продолжает ссылаться на тот текст, который ему
    # показывали, а не на актуальный.
    consent_doc, privacy_doc = await _publish_documents(uow_factory, '1.0')
    reg = RegistrationUseCases(uow_factory, FakeVkGateway())
    user = await reg.self_register(
        RegistrationData(
            vk_id=PLAYER_VK_ID,
            full_name='Иван Иванов',
            consent_document_id=consent_doc.id,
            privacy_policy_document_id=privacy_doc.id,
        )
    )
    await _publish_documents(uow_factory, '2.0')

    async with uow_factory() as uow:
        record = (await uow.consents.list_for_user(user.id))[0]
        accepted = await uow.legal_documents.get(record.consent_document_id)
        current = await uow.legal_documents.current(LegalDocumentKind.CONSENT)

    assert accepted.version == '1.0'
    assert accepted.content == '<html>consent 1.0</html>'
    assert current.version == '2.0'


@pytest.mark.asyncio
async def test_self_register_without_documents_writes_nothing(
    uow_factory: UowFactory,
) -> None:
    # Ручное добавление администратором (admin_add_user) не проходит через
    # чат-шаг согласия — версии документов там не передаются, и это не
    # должно приводить к ошибке или фиктивной записи в user_consents.
    reg = RegistrationUseCases(uow_factory, FakeVkGateway())

    user = await reg.self_register(
        RegistrationData(vk_id=PLAYER_VK_ID, full_name='Иван Иванов')
    )

    async with uow_factory() as uow:
        records = await uow.consents.list_for_user(user.id)

    assert records == []


@pytest.mark.asyncio
async def test_current_documents_returns_latest_versions(
    uow_factory: UowFactory,
) -> None:
    await _publish_documents(uow_factory, '1.0')
    await _publish_documents(uow_factory, '1.1')

    documents = await LegalUseCases(uow_factory).current_documents()

    assert documents.consent.version == '1.1'
    assert documents.privacy_policy.version == '1.1'


@pytest.mark.asyncio
async def test_current_documents_requires_both_documents(
    uow_factory: UowFactory,
) -> None:
    # Опубликовано только согласие: фиксировать согласие не с чем —
    # регистрация должна быть недоступна, а не записана наполовину.
    async with uow_factory() as uow:
        await uow.legal_documents.add(_document(LegalDocumentKind.CONSENT))
        await uow.commit()

    with pytest.raises(NotFoundError):
        await LegalUseCases(uow_factory).current_documents()
