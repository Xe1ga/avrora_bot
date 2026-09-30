"""Тесты дней рождения: подписки поздравителей и напоминания."""

from collections.abc import Callable
from datetime import date, datetime

import pytest

from avrora_bot.app import _seconds_until_birthday_check
from avrora_bot.application.use_cases.birthdays import BirthdayUseCases
from avrora_bot.application.use_cases.registration import (
    RegistrationData,
    RegistrationUseCases,
)
from avrora_bot.application.use_cases.roles import RoleUseCases
from avrora_bot.application.use_cases.user_management import (
    UserManagementUseCases,
)
from avrora_bot.domain.enums import RoleName
from avrora_bot.domain.errors import PermissionDeniedError, ValidationError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.services.birthday_calc import (
    birthday_in_year,
    is_last_day_of_month,
    is_next_month,
    next_birthday,
)
from tests.conftest import FakeVkGateway

ADMIN_VK_ID = 1
GREETER_VK_ID = 101
OTHER_GREETER_VK_ID = 102
IVANOV_VK_ID = 201
PETROV_VK_ID = 202
SIDOROV_VK_ID = 203

UowFactory = Callable[[], UnitOfWork]

_PEOPLE = [
    (GREETER_VK_ID, 'Поздравитель Первый', date(1990, 3, 3)),
    (OTHER_GREETER_VK_ID, 'Поздравитель Второй', date(1991, 4, 4)),
    (IVANOV_VK_ID, 'Иванов Иван', date(1996, 10, 10)),
    (PETROV_VK_ID, 'Петров Пётр', date(2000, 11, 5)),
    (SIDOROV_VK_ID, 'Сидоров Сидор', None),
]


async def _prepare(
    uow_factory: UowFactory, vk: FakeVkGateway
) -> BirthdayUseCases:
    reg = RegistrationUseCases(uow_factory, vk)
    roles = RoleUseCases(uow_factory, vk)
    for vk_id, name, birthdate in _PEOPLE:
        await reg.self_register(
            RegistrationData(vk_id=vk_id, full_name=name, birthdate=birthdate)
        )
        await reg.approve(ADMIN_VK_ID, vk_id)
    for vk_id in (GREETER_VK_ID, OTHER_GREETER_VK_ID):
        await roles.assign_role(ADMIN_VK_ID, vk_id, RoleName.GREETER)
    return BirthdayUseCases(uow_factory, vk)


def _messages(vk: FakeVkGateway, vk_id: int) -> list[str]:
    return [text for peer, text in vk.sent if peer == vk_id]


def test_next_birthday_this_and_next_year() -> None:
    born = date(1990, 10, 10)
    assert next_birthday(born, date(2026, 9, 30)) == date(2026, 10, 10)
    assert next_birthday(born, date(2026, 10, 10)) == date(2026, 10, 10)
    assert next_birthday(born, date(2026, 10, 11)) == date(2027, 10, 10)
    # Переход через новый год: 5 января из конца декабря.
    assert next_birthday(date(1990, 1, 5), date(2026, 12, 28)) == date(
        2027, 1, 5
    )


def test_leap_day_birthday_falls_on_feb_28_in_common_year() -> None:
    born = date(2000, 2, 29)
    assert birthday_in_year(born, 2027) == date(2027, 2, 28)
    assert birthday_in_year(born, 2028) == date(2028, 2, 29)
    assert next_birthday(born, date(2027, 2, 28)) == date(2027, 2, 28)
    assert next_birthday(born, date(2027, 3, 1)) == date(2028, 2, 29)


def test_month_helpers() -> None:
    assert is_last_day_of_month(date(2026, 9, 30))
    assert not is_last_day_of_month(date(2026, 10, 30))
    assert is_last_day_of_month(date(2027, 2, 28))
    assert is_next_month(date(2027, 1, 5), date(2026, 12, 31))
    assert not is_next_month(date(2026, 12, 5), date(2026, 10, 31))


def test_birthday_check_waits_for_ten_oclock() -> None:
    assert _seconds_until_birthday_check(datetime(2026, 9, 30, 9, 30)) == 1800
    assert _seconds_until_birthday_check(datetime(2026, 9, 30, 10, 0)) == 0
    assert _seconds_until_birthday_check(datetime(2026, 9, 30, 23, 59)) == 0


@pytest.mark.asyncio
async def test_subscribe_reports_added_already_and_missing_birthdate(
    uow_factory: UowFactory,
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    birthdays = await _prepare(uow_factory, vk)

    first = await birthdays.subscribe(GREETER_VK_ID, ['Иванов', 'Сидоров'])
    second = await birthdays.subscribe(
        GREETER_VK_ID, ['иванов иван', str(PETROV_VK_ID)]
    )

    assert [u.full_name for u in first.added] == [
        'Иванов Иван',
        'Сидоров Сидор',
    ]
    assert [u.full_name for u in first.without_birthdate] == ['Сидоров Сидор']
    assert [u.full_name for u in second.added] == ['Петров Пётр']
    assert [u.full_name for u in second.already] == ['Иванов Иван']


@pytest.mark.asyncio
async def test_subscribe_rejects_whole_list_on_unknown_name(
    uow_factory: UowFactory,
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    birthdays = await _prepare(uow_factory, vk)

    with pytest.raises(ValidationError):
        await birthdays.subscribe(GREETER_VK_ID, ['Иванов', 'Неизвестный'])

    assert await birthdays.list_tracked(GREETER_VK_ID, date(2026, 9, 30)) == []


@pytest.mark.asyncio
async def test_section_requires_greeter_role(uow_factory: UowFactory) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    birthdays = await _prepare(uow_factory, vk)

    with pytest.raises(PermissionDeniedError):
        await birthdays.subscribe(IVANOV_VK_ID, ['Петров'])
    with pytest.raises(PermissionDeniedError):
        await birthdays.list_tracked(IVANOV_VK_ID, date(2026, 9, 30))


@pytest.mark.asyncio
async def test_lists_of_different_greeters_are_independent(
    uow_factory: UowFactory,
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    birthdays = await _prepare(uow_factory, vk)
    today = date(2026, 9, 30)

    await birthdays.subscribe(GREETER_VK_ID, ['Иванов', 'Петров'])
    await birthdays.subscribe(OTHER_GREETER_VK_ID, ['Петров'])
    await birthdays.unsubscribe(GREETER_VK_ID, ['Петров'])

    first = await birthdays.list_tracked(GREETER_VK_ID, today)
    second = await birthdays.list_tracked(OTHER_GREETER_VK_ID, today)
    assert [row.user.full_name for row in first] == ['Иванов Иван']
    assert [row.user.full_name for row in second] == ['Петров Пётр']


@pytest.mark.asyncio
async def test_subscribe_all_adds_active_users_except_self(
    uow_factory: UowFactory,
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    birthdays = await _prepare(uow_factory, vk)

    result = await birthdays.subscribe_all(GREETER_VK_ID)
    rows = await birthdays.list_tracked(GREETER_VK_ID, date(2026, 9, 30))

    assert len(result.added) == len(_PEOPLE) - 1
    # Ближайшие — первыми, без даты рождения — в конце.
    assert [row.user.full_name for row in rows] == [
        'Иванов Иван',
        'Петров Пётр',
        'Поздравитель Второй',
        'Сидоров Сидор',
    ]
    assert rows[0].days_left == 10
    assert rows[-1].occasion is None


@pytest.mark.asyncio
async def test_unsubscribe_searches_only_tracked_and_is_atomic(
    uow_factory: UowFactory,
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    birthdays = await _prepare(uow_factory, vk)
    today = date(2026, 9, 30)
    await birthdays.subscribe(GREETER_VK_ID, ['Иванов', 'Петров'])

    # Сидоров существует, но в списке его нет — отклоняется весь запрос.
    with pytest.raises(ValidationError, match='нет в списке'):
        await birthdays.unsubscribe(GREETER_VK_ID, ['Иванов', 'Сидоров'])
    assert len(await birthdays.list_tracked(GREETER_VK_ID, today)) == 2

    removed = await birthdays.unsubscribe(GREETER_VK_ID, ['иванов', 'Петров'])
    assert [u.full_name for u in removed] == ['Иванов Иван', 'Петров Пётр']
    assert await birthdays.list_tracked(GREETER_VK_ID, today) == []


@pytest.mark.asyncio
async def test_reminder_ten_days_before_sent_once(
    uow_factory: UowFactory,
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    birthdays = await _prepare(uow_factory, vk)
    await birthdays.subscribe(GREETER_VK_ID, ['Иванов'])
    vk.sent.clear()

    assert await birthdays.send_due_reminders(date(2026, 9, 29)) == 0
    assert await birthdays.send_due_reminders(date(2026, 9, 30)) == 1
    # Повторный проход в тот же день и на следующий — без дублей.
    assert await birthdays.send_due_reminders(date(2026, 9, 30)) == 0
    assert await birthdays.send_due_reminders(date(2026, 10, 1)) == 0

    (text,) = _messages(vk, GREETER_VK_ID)
    assert 'Скоро дни рождения' in text
    assert '10.10 (через 10 дней) — Иванов Иван, исполнится 30' in text
    # 30 сентября — последний день месяца: тот же ДР попадает и в сводку.
    assert 'Дни рождения в октябре' in text


@pytest.mark.asyncio
async def test_reminder_on_birthday_and_again_next_year(
    uow_factory: UowFactory,
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    birthdays = await _prepare(uow_factory, vk)
    await birthdays.subscribe(GREETER_VK_ID, ['Иванов'])
    await birthdays.send_due_reminders(date(2026, 10, 1))
    vk.sent.clear()

    assert await birthdays.send_due_reminders(date(2026, 10, 10)) == 1
    assert await birthdays.send_due_reminders(date(2026, 10, 10)) == 0
    assert await birthdays.send_due_reminders(date(2027, 9, 30)) == 1

    today_text, next_year_text = _messages(vk, GREETER_VK_ID)
    assert 'Сегодня день рождения' in today_text
    assert 'Иванов Иван — исполняется 30' in today_text
    assert 'исполнится 31' in next_year_text


@pytest.mark.asyncio
async def test_late_subscription_is_reminded_immediately(
    uow_factory: UowFactory,
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    birthdays = await _prepare(uow_factory, vk)
    await birthdays.subscribe(GREETER_VK_ID, ['Иванов'])
    vk.sent.clear()

    # Подписка оформлена, когда до ДР осталось 3 дня.
    assert await birthdays.send_due_reminders(date(2026, 10, 7)) == 1

    (text,) = _messages(vk, GREETER_VK_ID)
    assert '10.10 (через 3 дня) — Иванов Иван' in text


@pytest.mark.asyncio
async def test_month_digest_on_last_day_lists_next_month(
    uow_factory: UowFactory,
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    birthdays = await _prepare(uow_factory, vk)
    await birthdays.subscribe(GREETER_VK_ID, ['Иванов', 'Петров', 'Сидоров'])
    # Напоминание «за 10 дней» о Петрове (05.11) уходит 26 октября.
    assert await birthdays.send_due_reminders(date(2026, 10, 26)) == 1
    vk.sent.clear()

    assert await birthdays.send_due_reminders(date(2026, 10, 30)) == 0
    assert await birthdays.send_due_reminders(date(2026, 10, 31)) == 1
    assert await birthdays.send_due_reminders(date(2026, 10, 31)) == 0

    (text,) = _messages(vk, GREETER_VK_ID)
    assert text == (
        '📅 Дни рождения в ноябре:\n• 05.11 — Петров Пётр, исполнится 26'
    )


@pytest.mark.asyncio
async def test_each_greeter_gets_own_reminders(uow_factory: UowFactory) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    birthdays = await _prepare(uow_factory, vk)
    await birthdays.subscribe(GREETER_VK_ID, ['Иванов'])
    await birthdays.subscribe(OTHER_GREETER_VK_ID, ['Петров'])
    vk.sent.clear()

    assert await birthdays.send_due_reminders(date(2026, 10, 10)) == 1

    assert len(_messages(vk, GREETER_VK_ID)) == 1
    assert _messages(vk, OTHER_GREETER_VK_ID) == []


@pytest.mark.asyncio
async def test_failed_send_is_retried(uow_factory: UowFactory) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    birthdays = await _prepare(uow_factory, vk)
    await birthdays.subscribe(GREETER_VK_ID, ['Иванов'])
    vk.sent.clear()
    working_send = vk.send_message

    async def broken_send(peer_id: int, text: str) -> None:
        raise RuntimeError('vk is down')

    vk.send_message = broken_send  # type: ignore[method-assign]
    assert await birthdays.send_due_reminders(date(2026, 10, 10)) == 0
    vk.send_message = working_send  # type: ignore[method-assign]

    assert await birthdays.send_due_reminders(date(2026, 10, 10)) == 1
    assert len(_messages(vk, GREETER_VK_ID)) == 1


@pytest.mark.asyncio
async def test_revoked_role_stops_reminders_but_keeps_list(
    uow_factory: UowFactory,
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    birthdays = await _prepare(uow_factory, vk)
    roles = RoleUseCases(uow_factory, vk)
    await birthdays.subscribe(GREETER_VK_ID, ['Иванов'])
    vk.sent.clear()

    await roles.revoke_role(ADMIN_VK_ID, GREETER_VK_ID, RoleName.GREETER)
    assert await birthdays.send_due_reminders(date(2026, 10, 10)) == 0

    await roles.assign_role(ADMIN_VK_ID, GREETER_VK_ID, RoleName.GREETER)
    rows = await birthdays.list_tracked(GREETER_VK_ID, date(2026, 10, 10))
    assert [row.user.full_name for row in rows] == ['Иванов Иван']
    assert await birthdays.send_due_reminders(date(2026, 10, 10)) == 1


@pytest.mark.asyncio
async def test_personal_data_deletion_removes_subscriptions(
    uow_factory: UowFactory,
) -> None:
    vk = FakeVkGateway(admins={ADMIN_VK_ID})
    birthdays = await _prepare(uow_factory, vk)
    management = UserManagementUseCases(uow_factory, vk)
    await birthdays.subscribe(GREETER_VK_ID, ['Иванов', 'Петров'])
    await birthdays.send_due_reminders(date(2026, 10, 10))
    async with uow_factory() as uow:
        ivanov = await uow.users.get_by_vk_id(IVANOV_VK_ID)

    await management.delete_personal_data(ADMIN_VK_ID, ivanov.id)

    rows = await birthdays.list_tracked(GREETER_VK_ID, date(2026, 10, 10))
    assert [row.user.full_name for row in rows] == ['Петров Пётр']
    async with uow_factory() as uow:
        assert await uow.birthday_reminders.list_since(date(2026, 1, 1)) == []
    with pytest.raises(ValidationError, match='удалены'):
        await birthdays.subscribe(GREETER_VK_ID, [str(IVANOV_VK_ID)])
