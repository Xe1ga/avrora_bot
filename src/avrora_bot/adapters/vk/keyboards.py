"""Клавиатуры бота."""

from vkbottle import Keyboard, KeyboardButtonColor, OpenLink, Text

from avrora_bot.application.services.permissions import has_access
from avrora_bot.domain.enums import RoleName


def main_menu(roles: frozenset[RoleName] = frozenset()) -> str:
    """Главное меню (стартовая клавиатура).

    Набор кнопок зависит от ролей пользователя (``roles``, см.
    ``permissions.effective_roles``) — администратору видны разделы всех
    ролей (ТЗ 2: «Полный доступ ко всем функциям бота»), остальным — только
    свой раздел. Видимость кнопки — лишь UI-удобство: доступ всё равно
    проверяется в хендлере/use case'е при каждом действии, скрытая кнопка
    лишь убирает пункт из интерфейса тех, у кого нет нужной роли.
    """
    is_admin = has_access(roles, RoleName.ADMIN)
    is_collector = has_access(roles, RoleName.COLLECTOR)
    is_curator = has_access(roles, RoleName.CURATOR)

    kb = (
        Keyboard(one_time=False)
        .add(Text('📅 Календарь', payload={'cmd': 'calendar'}))
        .add(Text('💳 Мой статус', payload={'cmd': 'status'}))
        .row()
        .add(Text('📝 Регистрация', payload={'cmd': 'register'}))
        .row()
        .add(Text('ℹ️ Помощь', payload={'cmd': 'help'}))
    )
    if is_admin or is_collector or is_curator:
        kb = kb.row().add(
            Text('📋 Список игроков', payload={'cmd': 'players_list'})
        )
    if is_admin:
        kb = (
            kb.row()
            .add(Text('📋 Заявки', payload={'cmd': 'requests'}))
            .add(
                Text(
                    '🛠 Роли и добавление',
                    payload={'cmd': 'admin_help'},
                )
            )
            .row()
            .add(
                Text(
                    '✏️ Редактировать пользователя',
                    payload={'cmd': 'edit_user'},
                )
            )
        )
    if is_collector:
        kb = (
            kb.row()
            .add(
                Text(
                    '💰 Абонементы',
                    payload={'cmd': 'subscriptions_help'},
                )
            )
            .add(Text('🎫 Разовые', payload={'cmd': 'one_time_help'}))
            .row()
            .add(Text('📊 Отчёты', payload={'cmd': 'reports_help'}))
        )
    if is_curator:
        kb = kb.row().add(
            Text(
                '🗓 Календарь: команды',
                payload={'cmd': 'calendar_help'},
            )
        )
    return kb.get_json()


def consent(privacy_policy_url: str, pdn_consent_url: str) -> str:
    """Клавиатура шага согласия на обработку персональных данных.

    Кнопки-ссылки открывают текст документов в браузере (см. docs/legal/);
    «✅ Я согласен» — единственный способ продолжить регистрацию: согласие
    должно быть явным действием пользователя, а не подразумеваться самим
    фактом продолжения диалога (ст. 9 152-ФЗ).
    """
    kb = (
        Keyboard(one_time=False)
        .add(OpenLink(privacy_policy_url, '📄 Политика обработки ПД'))
        .row()
        .add(OpenLink(pdn_consent_url, '📄 Согласие на обработку ПД'))
        .row()
        .add(
            Text('✅ Я согласен', payload={'cmd': 'consent_agree'}),
            color=KeyboardButtonColor.POSITIVE,
        )
        .add(
            Text('Отмена', payload={'cmd': 'cancel'}),
            color=KeyboardButtonColor.NEGATIVE,
        )
    )
    return kb.get_json()


def schedule_link(url: str) -> str:
    """Инлайн-кнопка со ссылкой на HTML-страницу расписания.

    ВК не поддерживает произвольный текст ссылки внутри тела сообщения
    (синтаксис ``[url|текст]`` работает только для внутренних сущностей —
    id/club/doc, не для внешних доменов), поэтому вместо «голого» URL в
    тексте — отдельная кнопка-ссылка под сообщением.
    """
    kb = Keyboard(inline=True).add(OpenLink(url, '🌐 Расписание на сайте'))
    return kb.get_json()


def one_time_actions() -> str:
    """Инлайн-кнопки действий раздела «Разовые посещения».

    Идут под справкой раздела: каждая кнопка запускает диалог, в котором
    бот отдельным сообщением спрашивает недостающее (дату, участника,
    месяц) — то же делают текстовые команды «посетили [дата]»,
    «разовое оплатил <ФИО>» и «разовые отчёт <период>». «Отчёт в чат»
    ничего не спрашивает: сразу выводит список за текущий месяц, как
    команда «разовые <текущий месяц>».
    """
    kb = (
        Keyboard(inline=True)
        .add(Text('🎫 Посетили', payload={'cmd': 'one_time_visited'}))
        .add(
            Text('💵 Оплатил', payload={'cmd': 'one_time_paid'}),
            color=KeyboardButtonColor.POSITIVE,
        )
        .row()
        .add(Text('💬 Отчёт в чат', payload={'cmd': 'one_time_chat'}))
        .add(
            Text('📊 Отчёт xlsx', payload={'cmd': 'one_time_report'}),
            color=KeyboardButtonColor.PRIMARY,
        )
    )
    return kb.get_json()


def visit_date_prompt() -> str:
    """Клавиатура шага «дата посещения»: «Сегодня» и «Отмена».

    Текст кнопки «Сегодня» разбирает ``helpers.parse_visit_date`` — это
    обычное сообщение, отдельный хендлер кнопке не нужен.
    """
    kb = (
        Keyboard(one_time=True)
        .add(Text('Сегодня', payload={'cmd': 'one_time_visit_today'}))
        .add(
            Text('Отмена', payload={'cmd': 'cancel'}),
            color=KeyboardButtonColor.NEGATIVE,
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


def edit_visit_fields() -> str:
    """Инлайн-кнопки выбора редактируемого поля разового посещения."""
    kb = (
        Keyboard(inline=True)
        .add(Text('Дата', payload={'cmd': 'edit_visit_field', 'field': 'date'}))
        .add(
            Text(
                'Сумма',
                payload={'cmd': 'edit_visit_field', 'field': 'amount'},
            )
        )
        .row()
        .add(
            Text(
                'Сборщик оплаты',
                payload={'cmd': 'edit_visit_field', 'field': 'collector'},
            )
        )
        .add(
            Text(
                'Примечание',
                payload={'cmd': 'edit_visit_field', 'field': 'note'},
            )
        )
        .row()
        .add(
            Text(
                'Оплачено ✅',
                payload={'cmd': 'edit_visit_field', 'field': 'paid'},
            ),
            color=KeyboardButtonColor.POSITIVE,
        )
        .add(
            Text(
                'Не оплачено ❌',
                payload={'cmd': 'edit_visit_field', 'field': 'unpaid'},
            ),
            color=KeyboardButtonColor.NEGATIVE,
        )
        .row()
        .add(
            Text('✅ Готово', payload={'cmd': 'edit_visit_done'}),
            color=KeyboardButtonColor.POSITIVE,
        )
    )
    return kb.get_json()


# ВК ограничивает кнопку клавиатуры ~40 символами текста и не более 10
# строк на клавиатуру — при большем числе неоплативших список режется на
# страницы (см. subscription_mark_page).
_MARK_BUTTON_LABEL_MAX = 40
MARK_PAGE_SIZE = 6


def subscription_mark_page(
    rows: list[tuple[int, str]],
    selected: set[int],
    page: int,
) -> str:
    """Чекбокс-список неоплативших для массовой отметки оплаты.

    ``rows`` — пары (user_id, ФИО) тех, кто ещё не оплатил (порядок как в
    сводке); ``selected`` — id, уже отмеченные в текущем диалоге (см.
    ``SubscriptionState.MARK_SELECT``). У ВК Bot API нет callback-кнопок
    с редактированием сообщения на месте (это доступно только через
    Callback API сообщества, которого тут нет) — тап по имени или по
    «Все»/«Никого» присылает боту новое сообщение с обновлённым payload,
    и бот перерисовывает список новым сообщением, как и ``edit_user_fields``.
    """
    total_pages = max(1, -(-len(rows) // MARK_PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    start = page * MARK_PAGE_SIZE
    page_rows = rows[start : start + MARK_PAGE_SIZE]

    kb = Keyboard(inline=True)
    for i, (user_id, full_name) in enumerate(page_rows):
        if i > 0:
            kb = kb.row()
        mark = '☑️' if user_id in selected else '⬜'
        label = f'{mark} {full_name}'[:_MARK_BUTTON_LABEL_MAX]
        kb = kb.add(Text(label, payload={'cmd': 'sub_toggle', 'user_id': user_id}))

    if total_pages > 1:
        kb = kb.row()
        if page > 0:
            kb = kb.add(
                Text('◀ Назад', payload={'cmd': 'sub_page', 'page': page - 1})
            )
        if page < total_pages - 1:
            kb = kb.add(
                Text('Дальше ▶', payload={'cmd': 'sub_page', 'page': page + 1})
            )

    kb = (
        kb.row()
        .add(Text('☑️ Все', payload={'cmd': 'sub_select_all'}))
        .add(Text('⬜ Никого', payload={'cmd': 'sub_select_none'}))
    )
    kb = (
        kb.row()
        .add(
            Text('💾 Отметить оплаченными', payload={'cmd': 'sub_confirm'}),
            color=KeyboardButtonColor.POSITIVE,
        )
        .add(
            Text('Отмена', payload={'cmd': 'cancel'}),
            color=KeyboardButtonColor.NEGATIVE,
        )
    )
    return kb.get_json()
