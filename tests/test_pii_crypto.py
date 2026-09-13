"""Тесты AES-256-GCM шифрования персональных данных."""

import base64

import pytest

from avrora_bot.adapters.database.crypto import (
    InvalidPiiKeyError,
    PiiCipher,
    decode_pii_key,
)

_KEY = b'k' * 32


def test_encrypt_decrypt_roundtrip() -> None:
    cipher = PiiCipher(_KEY)
    blob = cipher.encrypt_str('Иванов Иван Иванович')
    assert cipher.decrypt_str(blob) == 'Иванов Иван Иванович'


def test_ciphertext_does_not_contain_plaintext() -> None:
    cipher = PiiCipher(_KEY)
    plaintext = 'Иванов Иван Иванович'
    blob = cipher.encrypt_str(plaintext)
    assert plaintext.encode('utf-8') not in blob


def test_nonce_is_random_each_call() -> None:
    cipher = PiiCipher(_KEY)
    blob1 = cipher.encrypt_str('+7 900 000-00-00')
    blob2 = cipher.encrypt_str('+7 900 000-00-00')
    assert blob1 != blob2


def test_encrypt_opt_and_decrypt_opt_roundtrip_none() -> None:
    cipher = PiiCipher(_KEY)
    assert cipher.encrypt_opt(None) is None
    assert cipher.decrypt_opt(None) is None

    blob = cipher.encrypt_opt('+79000000000')
    assert cipher.decrypt_opt(blob) == '+79000000000'


def test_decode_pii_key_valid_base64_32_bytes() -> None:
    raw = base64.b64encode(_KEY).decode()
    assert decode_pii_key(raw) == _KEY


def test_decode_pii_key_rejects_invalid_base64() -> None:
    with pytest.raises(InvalidPiiKeyError):
        decode_pii_key('not-base64!!!')


def test_decode_pii_key_rejects_wrong_length() -> None:
    raw = base64.b64encode(b'short').decode()
    with pytest.raises(InvalidPiiKeyError):
        decode_pii_key(raw)
