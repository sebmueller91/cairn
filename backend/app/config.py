from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_path: str = "/data/cairn.db"
    api_token: str = "dev-token"
    api_token_readonly: str | None = None
    enable_scheduler: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
