"""Группы состояний диалогов (FSM) для vkbottle."""

from vkbottle import BaseStateGroup


class RegistrationState(BaseStateGroup):
    """Пошаговая самостоятельная регистрация игрока."""

    CONSENT = 'consent'
    FULL_NAME = 'full_name'
    BIRTHDATE = 'birthdate'
    HEIGHT = 'height'
    PHONE = 'phone'


class UserEditState(BaseStateGroup):
    """Редактирование данных пользователя администратором.

    Значения состояний используют собственный префикс ``user_edit:``, чтобы
    не совпадать с состояниями ``RegistrationState`` — обе группы могут быть
    активны одновременно (у разных пользователей), а ``BuiltinStateDispenser``
    сравнивает состояния как обычные строки.
    """

    SELECT_USER = 'user_edit:select_user'
    SELECT_FIELD = 'user_edit:select_field'
    FULL_NAME = 'user_edit:full_name'
    BIRTHDATE = 'user_edit:birthdate'
    HEIGHT = 'user_edit:height'
    PHONE = 'user_edit:phone'


class AdminState(BaseStateGroup):
    """Подтверждения необратимых административных действий."""

    # Ожидание явного текста «ПОДТВЕРЖДАЮ» перед уничтожением персональных
    # данных пользователя (ТЗ 3.6, 152-ФЗ) — см. handlers/admin.py.
    CONFIRM_DELETE_USER = 'admin:confirm_delete_user'


class SubscriptionState(BaseStateGroup):
    """Пошаговая фиксация голосования по абонементу (ТЗ 3.2)."""

    # Ожидание списка vk_id проголосовавших после команды «голоса <period>»
    # — см. handlers/subscriptions.py.
    VOTERS = 'subscription:voters'
