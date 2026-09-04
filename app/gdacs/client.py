from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings

log = logging.getLogger(__name__)

EVENTS4APP_PATH = "/events/geteventlist/EVENTS4APP"
SEARCH_PATH = "/events/geteventlist/SEARCH"
GEOMETRY_PATH = "/polygons/getgeometry"


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


class GDACSClient:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._client = httpx.Client(
            base_url=self.settings.gdacs_base_url.rstrip("/"),
            timeout=self.settings.gdacs_request_timeout_seconds,
            headers={"Accept": "application/geo+json, application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GDACSClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception(_should_retry),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _get_json(self, path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        response = self._client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Expected JSON object from {path}, got {type(payload).__name__}")
        return payload

    def fetch_events4app(self) -> list[dict[str, Any]]:
        log.info("Fetching GDACS EVENTS4APP feed")
        payload = self._get_json(EVENTS4APP_PATH)
        features = payload.get("features", [])
        if not isinstance(features, list):
            return []
        log.info("Received %d events from EVENTS4APP", len(features))
        return features

    def search_events(
        self,
        *,
        from_date: str,
        to_date: str,
        country: str,
        event_list: str,
        page_number: int = 1,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        params = {
            "country": country,
            "eventlist": event_list,
            "fromdate": from_date,
            "todate": to_date,
            "pagenumber": page_number,
            "pagesize": page_size,
        }
        log.info(
            "Searching GDACS events country=%s page=%d from=%s to=%s",
            country,
            page_number,
            from_date,
            to_date,
        )
        payload = self._get_json(SEARCH_PATH, params=params)
        features = payload.get("features", [])
        if not isinstance(features, list):
            return []
        log.info("Received %d events from SEARCH page %d", len(features), page_number)
        return features

    def fetch_geometry(
        self,
        *,
        event_type: str,
        event_id: int,
        episode_id: int,
        geometry_url: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        try:
            if geometry_url:
                response = self._client.get(geometry_url)
                response.raise_for_status()
                payload = response.json()
            else:
                payload = self._get_json(
                    GEOMETRY_PATH,
                    params={
                        "eventtype": event_type,
                        "eventid": event_id,
                        "episodeid": episode_id,
                    },
                )
        except (httpx.HTTPError, ValueError) as exc:
            log.warning(
                "Polygon fetch failed for %s/%s/%s: %s",
                event_type,
                event_id,
                episode_id,
                exc,
            )
            return None

        features = payload.get("features") if isinstance(payload, dict) else None
        if not features:
            return None
        geometry = features[0].get("geometry") if isinstance(features[0], dict) else None
        return geometry if isinstance(geometry, dict) else None

    def polite_delay(self) -> None:
        time.sleep(self.settings.gdacs_request_delay_seconds)
