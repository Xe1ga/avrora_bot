"""Группы состояний диалогов (FSM) для vkbottle."""

from vkbottle import BaseStateGroup


class RegistrationState(BaseStateGroup):
    """Пошаговая самостоятельная регистрация игрока."""

    FULL_NAME = 'full_name'
    BIRTHDATE = 'birthdate'
    HEIGHT = 'height'
    PHONE = 'phone'
