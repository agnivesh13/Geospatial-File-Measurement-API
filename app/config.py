"""Runtime settings. Every value can be overridden with an environment variable prefixed ``GEO_``
(for example ``GEO_DATABASE_URL=postgresql+psycopg://...``)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

MEGABYTE = 1024 * 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GEO_")

    database_url: str = "sqlite:///./data/geofiles.db"
    max_upload_bytes: int = 50 * MEGABYTE
    # Total size a zip may expand to. Guards against zip bombs (see app/geo/archive.py).
    max_uncompressed_bytes: int = 500 * MEGABYTE


@lru_cache
def get_settings() -> Settings:
    return Settings()
