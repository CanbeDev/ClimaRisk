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
    def _get(self, url: str, params: Optional[dict[str, Any]] = None) -> httpx.Response:
        """Shared retrying GET — used for both relative API paths and the absolute
        per-feature `geometry_url` GDACS hands back, so a transient 429/5xx is retried
        the same way regardless of which one a caller is fetching."""
        response = self._client.get(url, params=params)
        response.raise_for_status()
        return response

    def _get_json(self, path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        response = self._get(path, params=params)
        if response.status_code == 204:
            log.info("Received 204 No Content from %s", path)
            return {}
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
        # NOTE: GDACS's SEARCH `country` filter expects a full country name
        # (e.g. "South Africa"), not an ISO3 code, and silently returns 204
        # No Content for any ISO3 value. We fetch globally instead and rely
        # on event_affects_country() (ISO3-based, applied in process_features)
        # to do the real filtering locally — the same logic already used for
        # the realtime EVENTS4APP path. `country` is kept as an argument for
        # logging only; it is intentionally NOT sent to GDACS.
        params = {
            "eventlist": event_list,
            "fromdate": from_date,
            "todate": to_date,
            "pagenumber": page_number,
            "pagesize": page_size,
        }
        log.info(
            "Searching GDACS events (global, filtering locally for %s) page=%d from=%s to=%s",
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
                response = self._get(geometry_url)
                if response.status_code == 204:
                    log.info("Received 204 No Content from %s", geometry_url)
                    return None
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

        # GDACS's geometry endpoint puts the bare event marker (a Point) in
        # features[0] and the real area footprint (Polygon/MultiPolygon) in
        # later features — for cyclones interleaved with forecast-track
        # LineStrings too. Prefer the first real area footprint; fall back
        # to whatever geometry is available (e.g. a lone Point) if no
        # polygon/multipolygon feature exists at all.
        polygon_types = {"Polygon", "MultiPolygon"}
        fallback_geometry: Optional[dict[str, Any]] = None
        for feature in features:
            if not isinstance(feature, dict):
                continue
            geometry = feature.get("geometry")
            if not isinstance(geometry, dict):
                continue
            if fallback_geometry is None:
                fallback_geometry = geometry
            if geometry.get("type") in polygon_types:
                return geometry
        return fallback_geometry

    def polite_delay(self) -> None:
        time.sleep(self.settings.gdacs_request_delay_seconds)
