"""Поиск участника по vk_id или по (части) ФИО в командах сборщика (ТЗ 3.2).

Сборщику платежей неудобно держать под рукой vk_id каждого игрока — командам
над списком проголосовавших и отметками оплаты нужно принимать то же, что
он и так помнит: фамилию, «Фамилия Имя» или полное ФИО.
"""

from avrora_bot.domain.entities import User
from avrora_bot.domain.errors import NotFoundError, ValidationError
from avrora_bot.domain.ports.uow import UnitOfWork


async def resolve_user(uow: UnitOfWork, query: str) -> User:
    """Находит пользователя по vk_id (число) или по фрагменту ФИО.

    Фрагмент ищется без учёта регистра как подстрока полного ФИО — подходит
    фамилия, «Фамилия Имя» или ФИО целиком, в том порядке, в котором оно
    записано в профиле (Фамилия Имя [Отчество]).

    :raises NotFoundError: если совпадений нет.
    :raises ValidationError: если запрос пуст или совпадений несколько —
        сборщику нужно уточнить ФИО или назвать vk_id напрямую.
    """
    query = query.strip()
    if not query:
        raise ValidationError('Не указан vk_id или ФИО')
    if query.isdigit():
        user = await uow.users.get_by_vk_id(int(query))
        if user is None:
            raise NotFoundError(f'Пользователь с vk_id {query} не найден')
        return user

    needle = query.lower()
    matches = [
        user
        for user in await uow.users.list_all()
        if needle in user.full_name.lower()
    ]
    if not matches:
        raise NotFoundError(f'Пользователь «{query}» не найден')
    if len(matches) > 1:
        candidates = '\n'.join(
            f'  {user.full_name} ({vk_id_label(user.vk_id)})'
            for user in matches
        )
        raise ValidationError(
            f'Найдено несколько совпадений для «{query}»:\n{candidates}\n'
            'Уточните ФИО или укажите vk_id.'
        )
    return matches[0]


async def resolve_users(uow: UnitOfWork, queries: list[str]) -> list[User]:
    """Резолвит список vk_id/ФИО (например, из ``helpers.parse_targets``).

    Все запросы проверяются перед тем, как что-либо возвращать: если хотя
    бы один не найден или неоднозначен, поднимается единая
    ``ValidationError`` со всеми проблемами сразу, а не только первой —
    вызывающий код (``register_voting``, ``register_visits``) обычно
    должен отклонить весь список целиком, а не сохранить часть и заставить
    сборщика разбираться, кто из уже сохранённых лишний. Дубликаты одного
    и того же человека (например, один раз по vk_id, другой — по ФИО)
    схлопываются по итоговому ``id``.

    :raises ValidationError: если список пуст, или хотя бы один запрос не
        резолвится однозначно (текст ошибки перечисляет все проблемы).
    """
    unique_queries = list(
        dict.fromkeys(q.strip() for q in queries if q.strip())
    )
    if not unique_queries:
        raise ValidationError('Список пуст')

    resolved: list[User] = []
    errors: list[str] = []
    for query in unique_queries:
        try:
            resolved.append(await resolve_user(uow, query))
        except (NotFoundError, ValidationError) as exc:
            errors.append(f'«{query}»: {exc}')
    if errors:
        raise ValidationError('\n'.join(errors))

    users: list[User] = []
    seen_ids: set[int] = set()
    for user in resolved:
        if user.id not in seen_ids:
            seen_ids.add(user.id)
            users.append(user)
    return users


def vk_id_label(vk_id: int | None) -> str:
    """Подпись vk_id для сообщений — «без vk_id» у ручного игрока."""
    if vk_id is None:
        return 'без vk_id'
    return f'vk_id {vk_id}'
