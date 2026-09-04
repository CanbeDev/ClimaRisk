from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://climrisk_app:changeme@localhost:5432/climrisk"

    gdacs_base_url: str = "https://www.gdacs.org/gdacsapi/api"
    gdacs_country_filter: str = "ZAF"
    gdacs_event_types: str = "EQ;TC;FL;VO;WF;DR"
    gdacs_poll_interval_hours: int = 2
    gdacs_polygon_interval_hours: int = 6
    gdacs_request_timeout_seconds: float = 15.0
    gdacs_request_delay_seconds: float = 0.5
    gdacs_http_retries: int = 3

    ingest_commit_chunk_size: int = 20
    scheduler_enabled: bool = True

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
