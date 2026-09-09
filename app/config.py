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
    gdacs_request_timeout_seconds: float = 30.0
    gdacs_request_delay_seconds: float = 0.5
    gdacs_http_retries: int = 3

    ingest_commit_chunk_size: int = 20
    scheduler_enabled: bool = True

    # Parametric trigger rules engine (Phase 2). When the scheduler is on, active
    # rules are re-evaluated against every stored event on this interval — set
    # after polygon enrichment's cadence so footprints are current first.
    parametric_auto_evaluate: bool = True
    parametric_interval_hours: int = 6

    # When set, POST/GET /ingest/* routes require a matching X-API-Key header. Left unset,
    # those routes stay open — matching today's behavior for local/dev use. Set this before
    # exposing the service outside a trusted network.
    ingest_api_key: str | None = None

    log_level: str = "INFO"

    # Comma-separated list of origins allowed to call the API (dashboard dev servers).
    cors_allowed_origins: str = "http://localhost:5173,http://localhost:3000"

    # Name printed on the climate disclosure report (Step 8 / Phase 3).
    report_org_name: str = "ClimRisk Demo Portfolio"


@lru_cache
def get_settings() -> Settings:
    return Settings()
