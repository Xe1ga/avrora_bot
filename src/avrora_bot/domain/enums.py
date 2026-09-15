"""Доменные перечисления."""

from enum import StrEnum


class RoleName(StrEnum):
    """Роли пользователей (см. ТЗ, раздел 2)."""

    ADMIN = 'admin'
    COLLECTOR = 'collector'  # сборщик платежей
    CURATOR = 'curator'  # куратор (ДР, календарь)
    PLAYER = 'player'  # игрок


class UserStatus(StrEnum):
    """Статус профиля пользователя в процессе регистрации."""

    PENDING = 'pending'  # заявка/добавлен, но не подтверждён
    ACTIVE = 'active'  # подтверждён администратором
    REJECTED = 'rejected'  # заявка отклонена
    # Персональные данные уничтожены по отзыву согласия (ТЗ 3.6, 152-ФЗ
    # ст. 21) — см. UserManagementUseCases.delete_personal_data. Строка
    # users сохраняется (нужна как якорь для FK из user_consents и истории
    # оплат), vk_id не трогается, ФИО/телефон/ДР/рост уничтожены, роли
    # сняты. Повторная self_register с тем же vk_id разрешена и переводит
    # статус обратно в pending.
    DELETED = 'deleted'


class PaymentStatus(StrEnum):
    """Статус оплаты (абонемент или разовое посещение)."""

    PAID = 'paid'
    UNPAID = 'unpaid'


class EventType(StrEnum):
    """Тип события календаря."""

    TRAINING = 'training'  # тренировка
    GAME = 'game'  # игра


class LegalDocumentKind(StrEnum):
    """Вид юридического документа, публикуемого в ``docs/legal/``."""

    CONSENT = 'consent'  # согласие на обработку ПД (consent.html)
    PRIVACY_POLICY = 'privacy_policy'  # политика ПД (privacy-policy.html)


class TariffKind(StrEnum):
    """Вид тарифа с историей изменений по дате начала действия."""

    HALL_HOUR = 'hall_hour'  # стоимость зала за час
    COACH_SESSION = 'coach_session'  # стоимость одной тренировки с тренером
    ONE_TIME = 'one_time'  # разовое посещение


class Weekday(StrEnum):
    """День недели для шаблона расписания (соответствует date.weekday())."""

    MONDAY = 'monday'
    TUESDAY = 'tuesday'
    WEDNESDAY = 'wednesday'
    THURSDAY = 'thursday'
    FRIDAY = 'friday'
    SATURDAY = 'saturday'
    SUNDAY = 'sunday'

    @property
    def index(self) -> int:
        """Индекс дня недели, совместимый с ``datetime.date.weekday()``."""
        return _WEEKDAY_ORDER.index(self)


_WEEKDAY_ORDER: tuple[Weekday, ...] = (
    Weekday.MONDAY,
    Weekday.TUESDAY,
    Weekday.WEDNESDAY,
    Weekday.THURSDAY,
    Weekday.FRIDAY,
    Weekday.SATURDAY,
    Weekday.SUNDAY,
)


def weekday_from_index(index: int) -> Weekday:
    """Возвращает ``Weekday`` по индексу ``date.weekday()`` (0=пн … 6=вс)."""
    return _WEEKDAY_ORDER[index]
