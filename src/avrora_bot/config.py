"""Конфигурация приложения из переменных окружения (.env).

Секреты (токен VK, пароль БД) хранятся как ``SecretStr`` и не попадают в
логи при случайном выводе объекта настроек. Файл ``.env`` не коммитится в
репозиторий (см. .gitignore), для шаблона используется ``.env.example``.
"""

from functools import lru_cache

from pydantic import SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки бота, БД и режима работы VK."""

    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore',
    )

    # --- VK ---
    vk_token: SecretStr
    vk_group_id: int
    # Режим приёма событий. По умолчанию Long Poll; Callback заложен, но выключен.
    vk_use_callback: bool = False
    vk_confirmation_token: SecretStr | None = None
    vk_secret_key: SecretStr | None = None

    # --- PostgreSQL ---
    postgres_host: str = 'localhost'
    postgres_port: int = 5432
    postgres_db: str = 'avrora_bot'
    postgres_user: str = 'avrora'
    postgres_password: SecretStr

    # --- Bootstrap первого администратора ---
    # vk_id пользователя, которому при старте назначается роль admin,
    # чтобы было кому управлять ролями остальных.
    bootstrap_admin_vk_id: int | None = None

    # --- Прочее ---
    rate_limit_per_sec: float = 1.0
    log_level: str = 'INFO'
    tz: str = 'Europe/Moscow'

    @field_validator(
        'vk_confirmation_token',
        'vk_secret_key',
        'bootstrap_admin_vk_id',
        mode='before',
    )
    @classmethod
    def _empty_str_to_none(cls, value: object) -> object:
        """Пустая строка в .env трактуется как отсутствие значения."""
        if isinstance(value, str) and value.strip() == '':
            return None
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_dsn(self) -> str:
        """DSN для асинхронного драйвера asyncpg."""
        pwd = self.postgres_password.get_secret_value()
        return (
            f'postgresql+asyncpg://{self.postgres_user}:{pwd}'
            f'@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}'
        )


@lru_cache
def get_settings() -> Settings:
    """Возвращает singleton настроек (кэшируется на процесс)."""
    return Settings()  # значения читаются из окружения/.env
