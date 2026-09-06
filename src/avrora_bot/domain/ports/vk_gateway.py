"""Порт шлюза VK — абстракция над вызовами VK API из доменной логики.

Позволяет слою приложения проверять права и отправлять документы, не завися
от конкретной библиотеки (vkbottle). Реализация — в ``adapters/vk/gateway.py``.
"""

from typing import Protocol


class VkGateway(Protocol):
    """Контракт взаимодействия с VK API."""

    async def is_group_admin(self, vk_id: int) -> bool:
        """Проверяет, является ли пользователь администратором сообщества.

        Право верифицируется на момент вызова через ``groups.getMembers``
        (ТЗ 3.1, 5.2) — не кэшируется статично.
        """
        ...

    async def send_message(self, peer_id: int, text: str) -> None:
        """Отправляет текстовое сообщение пользователю/в беседу."""
        ...

    async def send_document(
        self, peer_id: int, file_path: str, message: str = ''
    ) -> None:
        """Отправляет документ (напр. XLSX-отчёт) вложением."""
        ...
