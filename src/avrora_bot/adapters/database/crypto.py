"""Шифрование PII-полей (ФИО, телефон) на уровне приложения (AES-256-GCM).

Формат хранимого blob: ``nonce(12 байт) || ciphertext+tag``. Шифрование
недетерминированное (случайный nonce на каждый вызов) — это допустимо, так
как поиск/фильтрация пользователей по значению ФИО или телефона нигде в
проекте не выполняется (только по ``vk_id``).

Ключ (32 байта, AES-256) хранится в переменной окружения ``PII_ENCRYPTION_KEY``
в виде base64-строки (см. ``avrora_bot.config.Settings.pii_encryption_key``).
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_LEN = 32
_NONCE_LEN = 12


class InvalidPiiKeyError(ValueError):
    """``PII_ENCRYPTION_KEY`` отсутствует, не base64 или неверной длины."""


def decode_pii_key(raw_base64: str) -> bytes:
    """Декодирует base64-ключ и проверяет его длину (fail-fast при старте)."""
    try:
        key = base64.b64decode(raw_base64, validate=True)
    except Exception as exc:
        raise InvalidPiiKeyError(
            'PII_ENCRYPTION_KEY: значение не является корректной base64-строкой'
        ) from exc
    if len(key) != _KEY_LEN:
        raise InvalidPiiKeyError(
            f'PII_ENCRYPTION_KEY: ожидается {_KEY_LEN} байт после '
            f'base64-декодирования, получено {len(key)}'
        )
    return key


class PiiCipher:
    """Шифрование/расшифровка строковых персональных данных."""

    def __init__(self, key: bytes) -> None:
        self._aead = AESGCM(key)

    def encrypt_str(self, plaintext: str) -> bytes:
        """Шифрует строку, возвращает ``nonce || ciphertext+tag``."""
        nonce = os.urandom(_NONCE_LEN)
        ciphertext = self._aead.encrypt(nonce, plaintext.encode('utf-8'), None)
        return nonce + ciphertext

    def decrypt_str(self, blob: bytes) -> str:
        """Расшифровывает blob, полученный из ``encrypt_str``."""
        nonce, ciphertext = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
        return self._aead.decrypt(nonce, ciphertext, None).decode('utf-8')

    def encrypt_opt(self, plaintext: str | None) -> bytes | None:
        """Вариант ``encrypt_str`` для необязательных полей (``None`` → ``None``)."""
        return None if plaintext is None else self.encrypt_str(plaintext)

    def decrypt_opt(self, blob: bytes | None) -> str | None:
        """Вариант ``decrypt_str`` для необязательных полей (``None`` → ``None``)."""
        return None if blob is None else self.decrypt_str(blob)
