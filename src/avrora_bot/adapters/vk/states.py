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
    # Чекбокс-список неоплативших под командой «абонементы <period>» —
    # мультивыбор перед массовой отметкой оплаты, см. handlers/subscriptions.py.
    MARK_SELECT = 'subscription:mark_select'


class OneTimeState(BaseStateGroup):
    """Пошаговая регистрация разовых посещений списком (ТЗ 3.2 п.4)."""

    # Ожидание списка vk_id/ФИО посетивших после команды «посетили [дата]»
    # — по аналогии с SubscriptionState.VOTERS, см. handlers/one_time.py.
    VISITORS = 'one_time:visitors'
    # Кнопки раздела «Разовые»: «Посетили» спрашивает дату, «Оплатил» —
    # vk_id/ФИО участника; те же операции доступны текстовыми командами.
    VISIT_DATE = 'one_time:visit_date'
    PAID_TARGET = 'one_time:paid_target'


class OneTimePaymentEditState(BaseStateGroup):
    """Редактирование записи о разовом посещении по id (ТЗ 3.2 п.4).

    Собственный префикс ``one_time_edit:`` — как и у ``UserEditState`` —
    чтобы не совпадать с другими группами состояний.
    """

    SELECT_FIELD = 'one_time_edit:select_field'
    DATE = 'one_time_edit:date'
    AMOUNT = 'one_time_edit:amount'
    COLLECTOR = 'one_time_edit:collector'
    NOTE = 'one_time_edit:note'


class OneTimeReportState(BaseStateGroup):
    """Запрос периода для XLSX-отчёта по разовым посещениям (ТЗ 3.2 п.4).

    Отдельный префикс ``one_time_report:`` — как у остальных групп; месяц
    спрашивается отдельным сообщением после нажатия кнопки «Отчёт xlsx»
    в разделе «Разовые посещения», см. handlers/one_time.py.
    """

    PERIOD = 'one_time_report:period'
