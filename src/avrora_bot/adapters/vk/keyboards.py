"""Клавиатуры бота."""

from vkbottle import Keyboard, KeyboardButtonColor, Text


def main_menu() -> str:
    """Главное меню (стартовая клавиатура)."""
    kb = (
        Keyboard(one_time=False)
        .add(Text('📅 Календарь', payload={'cmd': 'calendar'}))
        .add(Text('💳 Мой статус', payload={'cmd': 'status'}))
        .row()
        .add(Text('📝 Регистрация', payload={'cmd': 'register'}))
        .row()
        .add(Text('ℹ️ Помощь', payload={'cmd': 'help'}))
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
