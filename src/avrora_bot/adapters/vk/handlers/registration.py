"""FSM самостоятельной регистрации игрока (ТЗ 3.6)."""

from datetime import date

from vkbottle import Bot
from vkbottle.bot import Message

from avrora_bot.adapters.vk import keyboards
from avrora_bot.adapters.vk.context import BotContext
from avrora_bot.adapters.vk.handlers import helpers
from avrora_bot.adapters.vk.states import RegistrationState
from avrora_bot.application.use_cases.registration import RegistrationData
from avrora_bot.domain.errors import DomainError


def register(
    bot: Bot,
    ctx: BotContext,
    *,
    privacy_policy_url: str,
    pdn_consent_url: str,
    pdn_consent_version: str,
) -> None:
    """Регистрирует хендлеры пошаговой регистрации."""
    dispenser = bot.state_dispenser

    async def _current_state(peer_id: int) -> str | None:
        peer = await dispenser.get(peer_id)
        if peer is None:
            return None
        state = peer.state
        return (
            state if isinstance(state, str) else getattr(state, 'state', None)
        )

    async def _main_menu(vk_id: int) -> str:
        roles = await ctx.user_management.effective_roles(vk_id)
        return keyboards.main_menu(roles=roles)

    @bot.on.message(payload={'cmd': 'cancel'})
    async def cancel_handler(message: Message) -> None:
        # Общий отменитель для любого активного FSM (регистрация,
        # редактирование пользователя и т. п.) — состояние проверяется как
        # обычная строка, без привязки к конкретной группе состояний.
        if await _current_state(message.peer_id) is not None:
            await dispenser.delete(message.peer_id)
            await message.answer(
                'Действие отменено.',
                keyboard=await _main_menu(message.from_id),
            )

    @bot.on.message(payload={'cmd': 'register'})
    @bot.on.message(text=['регистрация'])
    async def start_registration(message: Message) -> None:
        existing = await ctx.registration.get_profile(message.from_id)
        if existing is not None:
            await message.answer(
                'Вы уже зарегистрированы или заявка уже подана.'
            )
            return
        await dispenser.set(message.peer_id, RegistrationState.CONSENT)
        await message.answer(
            'Продолжая, вы соглашаетесь с Политикой обработки '
            'персональных данных и принимаете Согласие на обработку '
            'персональных данных.\n\n'
            'Пожалуйста, ознакомьтесь с документами по кнопкам ниже, '
            'а затем нажмите «✅ Я согласен», чтобы продолжить '
            'регистрацию.',
            keyboard=keyboards.consent(privacy_policy_url, pdn_consent_url),
        )

    @bot.on.message(
        payload={'cmd': 'consent_agree'}, state=RegistrationState.CONSENT
    )
    async def confirm_consent(message: Message) -> None:
        await dispenser.set(
            message.peer_id,
            RegistrationState.FULL_NAME,
            consent_version=pdn_consent_version,
        )
        await message.answer('Введите ваши ФИО:', keyboard=keyboards.cancel())

    @bot.on.message(state=RegistrationState.CONSENT)
    async def remind_consent(message: Message) -> None:
        # Любой другой текст на этом шаге — не отменяем FSM, а напоминаем,
        # что продолжить можно только явным нажатием «✅ Я согласен».
        await message.answer(
            'Чтобы продолжить регистрацию, ознакомьтесь с документами и '
            'нажмите «✅ Я согласен» на клавиатуре ниже.'
        )

    @bot.on.message(state=RegistrationState.FULL_NAME)
    async def step_full_name(message: Message) -> None:
        full_name = message.text.strip()
        if len(full_name) < 3:  # noqa: PLR2004
            await message.answer('Слишком короткое имя. Повторите ввод ФИО:')
            return
        peer = await dispenser.get(message.peer_id)
        await dispenser.set(
            message.peer_id,
            RegistrationState.BIRTHDATE,
            full_name=full_name,
            consent_version=peer.payload['consent_version'],
        )
        await message.answer('Дата рождения (ДД.ММ.ГГГГ):')

    @bot.on.message(state=RegistrationState.BIRTHDATE)
    async def step_birthdate(message: Message) -> None:
        peer = await dispenser.get(message.peer_id)
        try:
            birthdate = helpers.parse_birthdate(message.text)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}\nПовторите ввод даты рождения:')
            return
        await dispenser.set(
            message.peer_id,
            RegistrationState.HEIGHT,
            full_name=peer.payload['full_name'],
            birthdate=birthdate.isoformat(),
            consent_version=peer.payload['consent_version'],
        )
        await message.answer('Ваш рост (см):')

    @bot.on.message(state=RegistrationState.HEIGHT)
    async def step_height(message: Message) -> None:
        peer = await dispenser.get(message.peer_id)
        try:
            height = helpers.parse_height(message.text)
        except DomainError as exc:
            await message.answer(f'⚠️ {exc}\nПовторите ввод роста:')
            return
        await dispenser.set(
            message.peer_id,
            RegistrationState.PHONE,
            full_name=peer.payload['full_name'],
            birthdate=peer.payload['birthdate'],
            height=height,
            consent_version=peer.payload['consent_version'],
        )
        await message.answer('Телефон для связи:')

    @bot.on.message(state=RegistrationState.PHONE)
    async def step_phone(message: Message) -> None:
        peer = await dispenser.get(message.peer_id)
        phone = message.text.strip()
        payload = peer.payload
        await dispenser.delete(message.peer_id)
        try:
            await ctx.registration.self_register(
                RegistrationData(
                    vk_id=message.from_id,
                    full_name=payload['full_name'],
                    birthdate=date.fromisoformat(payload['birthdate']),
                    height_cm=int(payload['height']),
                    phone=phone,
                    consent_version=payload['consent_version'],
                )
            )
        except DomainError as exc:
            await message.answer(
                f'⚠️ {exc}', keyboard=await _main_menu(message.from_id)
            )
            return
        await message.answer(
            'Заявка отправлена! Ожидайте подтверждения администратором.',
            keyboard=await _main_menu(message.from_id),
        )
