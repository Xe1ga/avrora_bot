"""Тесты уничтожения персональных данных по отзыву согласия (152-ФЗ, ст. 21)."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest

from avrora_bot.adapters.database.seed import seed_reference_data
from avrora_bot.application.use_cases.registration import (
    RegistrationData,
    RegistrationUseCases,
)
from avrora_bot.application.use_cases.roles import RoleUseCases
from avrora_bot.application.use_cases.subscriptions import SubscriptionUseCases
from avrora_bot.application.use_cases.user_management import (
    UserManagementUseCases,
)
from avrora_bot.domain import entities as e
from avrora_bot.domain.enums import LegalDocumentKind, RoleName, UserStatus
from avrora_bot.domain.errors import (
    AlreadyExistsError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.value_objects import MonthPeriod
from tests.conftest import FakeVkGateway

ADMIN_VK_ID = 1
PLAYER_VK_ID = 101

UowFactory = Callable[[], UnitOfWork]


def _document(kind: LegalDocumentKind, version: str = '1.0') -> e.LegalDocument:
    return e.LegalDocument(
        kind=kind,
        version=version,
        sha256=f'{kind.value}-{version}-hash',
        content=f'<html>{kind.value} {version}</html>',
    )


async def _publish_documents(
    uow_factory: UowFactory, version: str = '1.0'
) -> tuple[e.LegalDocument, e.LegalDocument]:
    async with uow_factory() as uow:
        consent = await uow.legal_documents.add(
            _document(LegalDocumentKind.CONSENT, version)
        )
        privacy = await uow.legal_documents.add(
            _document(LegalDocumentKind.PRIVACY_POLICY, version)
        )
        await uow.commit()
    return consent, privacy


async def _register_active_player(
    reg: RegistrationUseCases,
    consent_doc: e.LegalDocument,
    privacy_doc: e.LegalDocument,
) -> e.User:
    await reg.self_register(
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
    return await reg.approve(ADMIN_VK_ID, PLAYER_VK_ID)


@pytest.mark.asyncio
async def test_delete_personal_data_anonymizes_and_revokes_roles(
    uow_factory: UowFactory,
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    consent_doc, privacy_doc = await _publish_documents(uow_factory)
    reg = RegistrationUseCases(uow_factory, vk)
    roles = RoleUseCases(uow_factory, vk)
    users = UserManagementUseCases(uow_factory, vk)
    player = await _register_active_player(reg, consent_doc, privacy_doc)
    await roles.assign_role(ADMIN_VK_ID, PLAYER_VK_ID, RoleName.COLLECTOR)

    deleted = await users.delete_personal_data(ADMIN_VK_ID, player.id)

    assert deleted.status is UserStatus.DELETED
    assert deleted.full_name != 'Иван Иванов'
    assert deleted.phone is None
    assert deleted.birthdate is None
    assert deleted.height_cm is None
    assert deleted.vk_id == PLAYER_VK_ID  # публичный id в VK — не трогаем
    assert deleted.roles == set()

    async with uow_factory() as uow:
        roles_of = await uow.roles.roles_of(deleted.id)
    assert roles_of == set()


@pytest.mark.asyncio
async def test_delete_personal_data_keeps_consent_and_payment_history(
    uow_factory: UowFactory,
) -> None:
    # Ради этого и была развилка: история оплат и запись о согласии должны
    # пережить уничтожение ПД — иначе ломается отчётность за прошлые
    # месяцы и теряется доказательство правомерности прошлой обработки.
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    async with uow_factory() as uow:
        await seed_reference_data(uow)
        await uow.commit()
    consent_doc, privacy_doc = await _publish_documents(uow_factory)
    reg = RegistrationUseCases(uow_factory, vk)
    users = UserManagementUseCases(uow_factory, vk)
    subs = SubscriptionUseCases(uow_factory, vk)
    player = await _register_active_player(reg, consent_doc, privacy_doc)
    period = MonthPeriod(2026, 9)
    await subs.calculate(ADMIN_VK_ID, period, voters=1)
    await subs.register_voting(ADMIN_VK_ID, period, [str(PLAYER_VK_ID)])
    await subs.set_fact_amount(ADMIN_VK_ID, period, Decimal('1000'))
    await subs.mark_payment(ADMIN_VK_ID, period, str(PLAYER_VK_ID), paid=True)

    deleted = await users.delete_personal_data(ADMIN_VK_ID, player.id)

    async with uow_factory() as uow:
        consents = await uow.consents.list_for_user(deleted.id)
        payment = await uow.subscriptions.get_payment(
            (await uow.subscriptions.get_for_month(period)).id, deleted.id
        )

    assert len(consents) == 1
    assert consents[0].consent_document_id == consent_doc.id
    assert payment is not None
    assert payment.status.value == 'paid'


@pytest.mark.asyncio
async def test_delete_personal_data_requires_admin(
    uow_factory: UowFactory,
) -> None:
    vk = FakeVkGateway()
    reg = RegistrationUseCases(uow_factory, vk)
    users = UserManagementUseCases(uow_factory, vk)
    await reg.self_register(
        RegistrationData(vk_id=PLAYER_VK_ID, full_name='Иван Иванов')
    )

    with pytest.raises(PermissionDeniedError):
        await users.delete_personal_data(PLAYER_VK_ID, PLAYER_VK_ID)


@pytest.mark.asyncio
async def test_delete_personal_data_unknown_user_raises_not_found(
    uow_factory: UowFactory,
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    users = UserManagementUseCases(uow_factory, vk)

    with pytest.raises(NotFoundError):
        await users.delete_personal_data(ADMIN_VK_ID, 999999)


@pytest.mark.asyncio
async def test_delete_personal_data_twice_raises_validation_error(
    uow_factory: UowFactory,
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    reg = RegistrationUseCases(uow_factory, vk)
    users = UserManagementUseCases(uow_factory, vk)
    player = await reg.self_register(
        RegistrationData(vk_id=PLAYER_VK_ID, full_name='Иван Иванов')
    )
    await users.delete_personal_data(ADMIN_VK_ID, player.id)

    with pytest.raises(ValidationError):
        await users.delete_personal_data(ADMIN_VK_ID, player.id)


@pytest.mark.asyncio
async def test_self_register_after_deletion_reuses_row_as_new_request(
    uow_factory: UowFactory,
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    consent_v1, privacy_v1 = await _publish_documents(uow_factory, '1.0')
    reg = RegistrationUseCases(uow_factory, vk)
    users = UserManagementUseCases(uow_factory, vk)
    first = await reg.self_register(
        RegistrationData(
            vk_id=PLAYER_VK_ID,
            full_name='Иван Иванов',
            consent_document_id=consent_v1.id,
            privacy_policy_document_id=privacy_v1.id,
        )
    )
    await users.delete_personal_data(ADMIN_VK_ID, first.id)

    consent_v2, privacy_v2 = await _publish_documents(uow_factory, '2.0')
    second = await reg.self_register(
        RegistrationData(
            vk_id=PLAYER_VK_ID,
            full_name='Иван Иванов Заново',
            phone='+79990000000',
            consent_document_id=consent_v2.id,
            privacy_policy_document_id=privacy_v2.id,
        )
    )

    assert second.id == first.id  # та же строка, не дубль
    assert second.status is UserStatus.PENDING
    assert second.full_name == 'Иван Иванов Заново'
    assert second.phone == '+79990000000'

    async with uow_factory() as uow:
        consents = await uow.consents.list_for_user(second.id)
    assert [c.consent_document_id for c in consents] == [
        consent_v1.id,
        consent_v2.id,
    ]  # старая запись о согласии не потерялась


@pytest.mark.asyncio
async def test_self_register_blocked_for_active_or_pending_user(
    uow_factory: UowFactory,
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    reg = RegistrationUseCases(uow_factory, vk)
    await reg.self_register(
        RegistrationData(vk_id=PLAYER_VK_ID, full_name='Иван Иванов')
    )

    with pytest.raises(AlreadyExistsError):
        await reg.self_register(
            RegistrationData(vk_id=PLAYER_VK_ID, full_name='Дубль')
        )
