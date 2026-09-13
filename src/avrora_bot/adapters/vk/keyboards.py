"""Клавиатуры бота."""

from vkbottle import Keyboard, KeyboardButtonColor, Text

from avrora_bot.domain.enums import RoleName


def main_menu(roles: frozenset[RoleName] = frozenset()) -> str:
    """Главное меню (стартовая клавиатура).

    Набор кнопок зависит от ролей пользователя (``roles``) — так пункты для
    новых ролей добавляются веткой ``if <роль> in roles``, без изменения
    сигнатуры. Видимость кнопки — лишь UI-удобство: доступ всё равно
    проверяется в хендлере/use case'е, скрытая кнопка лишь убирает её из
    интерфейса тех, у кого нет соответствующей роли.
    """
    kb = (
        Keyboard(one_time=False)
        .add(Text('📅 Календарь', payload={'cmd': 'calendar'}))
        .add(Text('💳 Мой статус', payload={'cmd': 'status'}))
        .row()
        .add(Text('📝 Регистрация', payload={'cmd': 'register'}))
        .row()
        .add(Text('ℹ️ Помощь', payload={'cmd': 'help'}))
    )
    if RoleName.ADMIN in roles:
        kb = kb.row().add(
            Text(
                '✏️ Редактировать пользователя',
                payload={'cmd': 'edit_user'},
            )
        )
    return kb.get_json()


def cancel() -> str:
    """Клавиатура с единственной кнопкой отмены."""
    kb = Keyboard(one_time=True).add(
        Text('Отмена', payload={'cmd': 'cancel'}),
        color=KeyboardButtonColor.NEGATIVE,
    )
    return kb.get_json()


def approve_reject(vk_id: int) -> str:
    """Инлайн-кнопки подтверждения/отклонения заявки для администратора."""
    kb = (
        Keyboard(inline=True)
        .add(
            Text(
                '✅ Подтвердить',
                payload={'cmd': 'approve', 'vk_id': vk_id},
            ),
            color=KeyboardButtonColor.POSITIVE,
        )
        .add(
            Text(
                '❌ Отклонить',
                payload={'cmd': 'reject', 'vk_id': vk_id},
            ),
            color=KeyboardButtonColor.NEGATIVE,
        )
    )
    return kb.get_json()


def edit_user_fields() -> str:
    """Инлайн-кнопки выбора редактируемого поля профиля."""
    kb = (
        Keyboard(inline=True)
        .add(Text('ФИО', payload={'cmd': 'edit_field', 'field': 'full_name'}))
        .add(Text('Телефон', payload={'cmd': 'edit_field', 'field': 'phone'}))
        .row()
        .add(
            Text(
                'Дата рождения',
                payload={'cmd': 'edit_field', 'field': 'birthdate'},
            )
        )
        .add(Text('Рост', payload={'cmd': 'edit_field', 'field': 'height'}))
        .row()
        .add(
            Text('✅ Готово', payload={'cmd': 'edit_done'}),
            color=KeyboardButtonColor.POSITIVE,
        )
    )
    return kb.get_json()
