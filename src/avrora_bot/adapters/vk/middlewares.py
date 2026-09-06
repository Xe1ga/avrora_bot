"""Middleware'ы: ограничение частоты команд (ТЗ 5.4)."""

import time

from vkbottle import BaseMiddleware
from vkbottle.bot import Message

from avrora_bot.logging_setup import get_logger

log = get_logger('vk_middleware')


class RateLimitMiddleware(BaseMiddleware[Message]):
    """Простое ограничение: не чаще одного события за ``min_interval`` секунд.

    Состояние — в памяти процесса (для клуба ~30 человек этого достаточно;
    при масштабировании выносится в Redis).
    """

    #: минимальный интервал между сообщениями одного peer, секунды
    min_interval: float = 1.0
    _last_seen: dict[int, float] = {}

    async def pre(self) -> None:
        peer_id = self.event.peer_id
        now = time.monotonic()
        last = self._last_seen.get(peer_id, 0.0)
        if now - last < self.min_interval:
            log.debug('rate_limited', peer_id=peer_id)
            self.stop('rate limited')
            return
        self._last_seen[peer_id] = now


def make_rate_limit_middleware(min_interval: float) -> type[BaseMiddleware]:
    """Создаёт класс middleware с заданным интервалом."""

    class _Configured(RateLimitMiddleware):
        pass

    _Configured.min_interval = min_interval
    _Configured._last_seen = {}
    return _Configured
