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
            f'  {user.full_name} (vk_id {user.vk_id})' for user in matches
        )
        raise ValidationError(
            f'Найдено несколько совпадений для «{query}»:\n{candidates}\n'
            'Уточните ФИО или укажите vk_id.'
        )
    return matches[0]
