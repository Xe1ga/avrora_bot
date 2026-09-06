"""Реализация порта ``VkGateway`` поверх vkbottle."""

from vkbottle import API, DocMessagesUploader

from avrora_bot.logging_setup import get_logger

log = get_logger('vk_gateway')

# Число случайных id для messages.send (0 = сгенерировать автоматически).
_AUTO_RANDOM_ID = 0


class VkbottleGateway:
    """Обёртка над VK API для проверки прав и отправки сообщений/документов."""

    def __init__(self, api: API, group_id: int) -> None:
        self._api = api
        self._group_id = group_id

    async def is_group_admin(self, vk_id: int) -> bool:
        """Проверяет, входит ли пользователь в управляющий состав сообщества.

        Право верифицируется на момент вызова через ``groups.getMembers``
        с фильтром ``managers`` (ТЗ 3.1, 5.2).
        """
        try:
            members = await self._api.groups.get_members(
                group_id=self._group_id, filter='managers'
            )
        except Exception:  # noqa: BLE001 — сеть/права VK: безопасный дефолт
            log.warning('vk.get_members_failed', vk_id=vk_id)
            return False
        return any(m.member_id == vk_id for m in members.items)

    async def send_message(self, peer_id: int, text: str) -> None:
        """Отправляет текстовое сообщение."""
        await self._api.messages.send(
            peer_id=peer_id, message=text, random_id=_AUTO_RANDOM_ID
        )

    async def send_document(
        self, peer_id: int, file_path: str, message: str = ''
    ) -> None:
        """Загружает и отправляет документ (напр. XLSX-отчёт)."""
        uploader = DocMessagesUploader(self._api)
        attachment = await uploader.upload(
            file_source=file_path, peer_id=peer_id
        )
        await self._api.messages.send(
            peer_id=peer_id,
            message=message,
            attachment=attachment,
            random_id=_AUTO_RANDOM_ID,
        )
