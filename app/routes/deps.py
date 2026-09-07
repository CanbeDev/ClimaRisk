from __future__ import annotations

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_ingest_api_key(provided_key: str | None = Security(_api_key_header)) -> None:
    """Gate the /ingest/* routes behind a shared-secret header.

    If INGEST_API_KEY isn't configured, this is a no-op (matches the previous open-by-default
    behavior for local/dev use). Once configured, every request must send a matching
    `X-API-Key` header or gets a 401 — these routes trigger real ingestion jobs and, unlike the
    read-only /hazards, /assets, /exposure endpoints, are worth locking down first.
    """
    settings = get_settings()
    if not settings.ingest_api_key:
        return
    if provided_key != settings.ingest_api_key:
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header")
