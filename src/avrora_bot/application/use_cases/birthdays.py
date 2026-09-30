"""Use case'ы дней рождения: подписки поздравителей и напоминания (ТЗ 3.4).

Поздравитель (роль ``greeter``, либо администратор) ведёт собственный
список отслеживаемых участников; списки разных поздравителей независимы.
По списку бот присылает напоминания: заранее (за 10 дней), в сам день
рождения и сводку на следующий месяц в последний день текущего — см.
``domain/services/birthday_calc.py``.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from avrora_bot.application.services import permissions
from avrora_bot.application.services.action_log import record_action
from avrora_bot.application.services.user_lookup import (
    resolve_users,
    vk_id_label,
)
from avrora_bot.domain.entities import BirthdayReminder, User
from avrora_bot.domain.enums import BirthdayReminderKind, RoleName, UserStatus
from avrora_bot.domain.errors import NotFoundError, ValidationError
from avrora_bot.domain.ports.uow import UnitOfWork
from avrora_bot.domain.ports.vk_gateway import VkGateway
from avrora_bot.domain.services.birthday_calc import (
    REMIND_DAYS_BEFORE,
    is_last_day_of_month,
    is_next_month,
    next_birthday,
    turning_age,
)
from avrora_bot.logging_setup import get_logger

log = get_logger('birthdays')

UowFactory = Callable[[], UnitOfWork]

_MONTHS_PREPOSITIONAL = (
    'январе',
    'феврале',
    'марте',
    'апреле',
    'мае',
    'июне',
    'июле',
    'августе',
    'сентябре',
    'октябре',
    'ноябре',
    'декабре',
)


@dataclass(frozen=True, slots=True)
class SubscribeResult:
    """Итог подписки: кто добавлен, кто уже был в списке."""

    added: list[User]
    already: list[User]

    @property
    def without_birthdate(self) -> list[User]:
        """Добавленные без даты рождения — напоминаний по ним пока не будет."""
        return [user for user in self.added if user.birthdate is None]


@dataclass(frozen=True, slots=True)
class TrackedBirthday:
    """Строка списка отслеживаемых: участник и его ближайший день рождения."""

    user: User
    occasion: date | None  # None — дата рождения не указана
    days_left: int | None


@dataclass(slots=True)
class _Digest:
    """Одно сообщение поздравителю и записи журнала, которые оно закрывает.

    Строки хранятся парами (дата ДР, текст) — для сортировки по дате.
    """

    subscriber: User
    today_lines: list[tuple[date, str]] = field(default_factory=list)
    soon_lines: list[tuple[date, str]] = field(default_factory=list)
    month_lines: list[tuple[date, str]] = field(default_factory=list)
    reminders: list[BirthdayReminder] = field(default_factory=list)


class BirthdayUseCases:
    """Подписки на дни рождения и рассылка напоминаний."""

    def __init__(self, uow_factory: UowFactory, vk_gateway: VkGateway) -> None:
        self._uow_factory = uow_factory
        self._vk = vk_gateway

    async def subscribe(
        self, actor_vk_id: int, targets: list[str]
    ) -> SubscribeResult:
        """Подписывает поздравителя на участников из списка vk_id/ФИО.

        Список принимается целиком или отклоняется целиком — как в
        ``resolve_users``: если хоть один запрос не найден или неоднозначен,
        ничего не сохраняется.
        """
        async with self._uow_factory() as uow:
            actor = await self._require_greeter(uow, actor_vk_id)
            users = await resolve_users(uow, targets)
            deleted = [u for u in users if u.status is UserStatus.DELETED]
            if deleted:
                labels = ', '.join(vk_id_label(u.vk_id) for u in deleted)
                raise ValidationError(
                    f'Персональные данные удалены, подписка невозможна: '
                    f'{labels}'
                )
            result = await self._add(uow, actor, users)
            await uow.commit()
            return result

    async def subscribe_all(self, actor_vk_id: int) -> SubscribeResult:
        """Подписывает на всех активных участников клуба (кроме себя).

        Это разовое добавление текущего состава: участников, появившихся
        позже, нужно добавить отдельно (или снова «подписаться на всех»).
        """
        async with self._uow_factory() as uow:
            actor = await self._require_greeter(uow, actor_vk_id)
            users = [
                user
                for user in await uow.users.list_by_status(UserStatus.ACTIVE)
                if user.id != actor.id
            ]
            result = await self._add(uow, actor, users)
            await uow.commit()
            return result

    async def unsubscribe(
        self, actor_vk_id: int, queries: list[str]
    ) -> list[User]:
        """Убирает участников из списка отслеживаемых поздравителя.

        Запросы (vk_id или часть ФИО, обычно фамилия) ищутся только среди
        уже отслеживаемых — однофамилец, на которого подписки нет, не
        мешает. Список принимается или отклоняется целиком.
        """
        async with self._uow_factory() as uow:
            actor = await self._require_greeter(uow, actor_vk_id)
            tracked = await self._tracked_users(uow, actor)
            unique_queries = list(
                dict.fromkeys(q.strip() for q in queries if q.strip())
            )
            if not unique_queries:
                raise ValidationError('Список пуст')

            found: dict[int, User] = {}
            errors: list[str] = []
            for query in unique_queries:
                try:
                    user = _match_tracked(tracked, query)
                except (NotFoundError, ValidationError) as exc:
                    errors.append(f'«{query}»: {exc}')
                else:
                    found[user.id] = user
            if errors:
                raise ValidationError('\n'.join(errors))

            for user in found.values():
                await uow.birthday_subscriptions.remove(actor.id, user.id)
            await record_action(
                uow,
                actor_vk_id,
                'birthdays.unsubscribe',
                f'user_ids={sorted(found)}',
            )
            await uow.commit()
            return sorted(found.values(), key=lambda user: user.full_name)

    async def list_tracked(
        self, actor_vk_id: int, today: date
    ) -> list[TrackedBirthday]:
        """Список отслеживаемых, ближайшие дни рождения — первыми."""
        async with self._uow_factory() as uow:
            actor = await self._require_greeter(uow, actor_vk_id)
            rows = [
                _tracked(user, today)
                for user in await self._tracked_users(uow, actor)
            ]
        return sorted(
            rows,
            key=lambda row: (
                row.days_left is None,
                row.days_left or 0,
                row.user.full_name,
            ),
        )

    async def send_due_reminders(self, today: date) -> int:
        """Рассылает поздравителям напоминания, положенные на ``today``.

        Каждому поздравителю — одно сообщение со всеми поводами сразу.
        Отправленное фиксируется в журнале ``birthday_reminders``; если
        отправка не удалась, записи нет — следующий проход повторит.
        Снятая роль поздравителя останавливает рассылку, список при этом
        сохраняется.

        :returns: число отправленных сообщений.
        """
        async with self._uow_factory() as uow:
            digests = await self._collect_digests(uow, today)

        sent = 0
        for digest in digests:
            subscriber = digest.subscriber
            try:
                await self._vk.send_message(
                    subscriber.vk_id, _digest_text(digest, today)
                )
            except Exception:
                log.exception(
                    'birthdays.reminder_failed', vk_id=subscriber.vk_id
                )
                continue
            async with self._uow_factory() as uow:
                for reminder in digest.reminders:
                    await uow.birthday_reminders.add(reminder)
                await uow.commit()
            sent += 1
        return sent

    async def _collect_digests(
        self, uow: UnitOfWork, today: date
    ) -> list[_Digest]:
        subscriptions = await uow.birthday_subscriptions.list_all()
        if not subscriptions:
            return []
        users = {user.id: user for user in await uow.users.list_all()}
        already_sent = {
            (r.subscriber_user_id, r.target_user_id, r.kind, r.occasion)
            for r in await uow.birthday_reminders.list_since(today)
        }
        month_digest_day = is_last_day_of_month(today)

        digests: dict[int, _Digest] = {}
        allowed: dict[int, bool] = {}
        for subscription in subscriptions:
            subscriber = users.get(subscription.subscriber_user_id)
            target = users.get(subscription.target_user_id)
            if (
                subscriber is None
                or target is None
                or target.birthdate is None
                or target.status is UserStatus.DELETED
            ):
                continue
            if subscriber.id not in allowed:
                allowed[subscriber.id] = await self._may_receive(
                    uow, subscriber
                )
            if not allowed[subscriber.id]:
                continue

            occasion = next_birthday(target.birthdate, today)
            days_left = (occasion - today).days
            age = turning_age(target.birthdate, occasion)
            day = occasion.strftime('%d.%m')
            digest = digests.setdefault(subscriber.id, _Digest(subscriber))

            due: list[tuple[BirthdayReminderKind, list[tuple[date, str]], str]]
            due = []
            if days_left == 0:
                due.append(
                    (
                        BirthdayReminderKind.ON_DAY,
                        digest.today_lines,
                        f'• {target.full_name} — исполняется {age}',
                    )
                )
            elif days_left <= REMIND_DAYS_BEFORE:
                due.append(
                    (
                        BirthdayReminderKind.TEN_DAYS,
                        digest.soon_lines,
                        f'• {day} (через {_days_label(days_left)}) — '
                        f'{target.full_name}, исполнится {age}',
                    )
                )
            if month_digest_day and is_next_month(occasion, today):
                due.append(
                    (
                        BirthdayReminderKind.NEXT_MONTH,
                        digest.month_lines,
                        f'• {day} — {target.full_name}, исполнится {age}',
                    )
                )
            for kind, lines, text in due:
                key = (subscriber.id, target.id, kind, occasion)
                if key in already_sent:
                    continue
                lines.append((occasion, text))
                digest.reminders.append(
                    BirthdayReminder(
                        subscriber_user_id=subscriber.id,
                        target_user_id=target.id,
                        kind=kind,
                        occasion=occasion,
                    )
                )
        return [d for d in digests.values() if d.reminders]

    async def _may_receive(self, uow: UnitOfWork, subscriber: User) -> bool:
        """Получает ли пользователь напоминания: есть vk_id и право."""
        if subscriber.vk_id is None or subscriber.status is UserStatus.DELETED:
            return False
        roles = await permissions.effective_roles(
            uow, self._vk, subscriber.vk_id
        )
        return permissions.has_access(roles, RoleName.GREETER)

    async def _require_greeter(self, uow: UnitOfWork, vk_id: int) -> User:
        await permissions.require_role(uow, self._vk, vk_id, RoleName.GREETER)
        actor = await uow.users.get_by_vk_id(vk_id)
        if actor is None:
            # Администратор сообщества VK без профиля в боте: список
            # привязывается к профилю, поэтому сначала нужна регистрация.
            raise NotFoundError(
                'У вас нет профиля в боте — сначала пройдите регистрацию'
            )
        return actor

    @staticmethod
    async def _tracked_users(uow: UnitOfWork, actor: User) -> list[User]:
        target_ids = await uow.birthday_subscriptions.target_ids_of(actor.id)
        if not target_ids:
            return []
        return [
            user for user in await uow.users.list_all() if user.id in target_ids
        ]

    @staticmethod
    async def _add(
        uow: UnitOfWork, actor: User, users: list[User]
    ) -> SubscribeResult:
        tracked = await uow.birthday_subscriptions.target_ids_of(actor.id)
        added = [user for user in users if user.id not in tracked]
        already = [user for user in users if user.id in tracked]
        for user in added:
            await uow.birthday_subscriptions.add(actor.id, user.id)
        if added:
            await record_action(
                uow,
                actor.vk_id,
                'birthdays.subscribe',
                f'user_ids={sorted(user.id for user in added)}',
            )
        return SubscribeResult(added=added, already=already)


def _tracked(user: User, today: date) -> TrackedBirthday:
    if user.birthdate is None:
        return TrackedBirthday(user=user, occasion=None, days_left=None)
    occasion = next_birthday(user.birthdate, today)
    return TrackedBirthday(
        user=user, occasion=occasion, days_left=(occasion - today).days
    )


def _match_tracked(tracked: list[User], query: str) -> User:
    """Ищет одного участника среди отслеживаемых по vk_id или части ФИО."""
    if query.isdigit():
        matches = [user for user in tracked if user.vk_id == int(query)]
    else:
        needle = query.lower()
        matches = [user for user in tracked if needle in user.full_name.lower()]
    if not matches:
        raise NotFoundError('нет в списке отслеживаемых')
    if len(matches) > 1:
        candidates = '\n'.join(
            f'  {user.full_name} ({vk_id_label(user.vk_id)})'
            for user in matches
        )
        raise ValidationError(
            f'в списке несколько совпадений:\n{candidates}\n'
            'Уточните ФИО или укажите vk_id.'
        )
    return matches[0]


def _days_label(days: int) -> str:
    """«1 день», «3 дня», «10 дней»."""
    tail, tens = days % 10, days % 100
    if tail == 1 and tens != 11:  # noqa: PLR2004
        word = 'день'
    elif tail in (2, 3, 4) and tens not in (12, 13, 14):
        word = 'дня'
    else:
        word = 'дней'
    return f'{days} {word}'


def days_left_label(days: int) -> str:
    """Подпись срока до дня рождения: «сегодня», «через 3 дня»."""
    return 'сегодня' if days == 0 else f'через {_days_label(days)}'


def _digest_text(digest: _Digest, today: date) -> str:
    # Сводка уходит в последний день месяца — называем следующий месяц.
    month = _MONTHS_PREPOSITIONAL[today.month % 12]
    sections = [
        ('🎂 Сегодня день рождения:', digest.today_lines),
        ('⏰ Скоро дни рождения:', digest.soon_lines),
        (f'📅 Дни рождения в {month}:', digest.month_lines),
    ]
    return '\n\n'.join(
        '\n'.join([title, *(text for _, text in sorted(lines))])
        for title, lines in sections
        if lines
    )
