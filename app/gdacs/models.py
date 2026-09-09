from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class HazardEvent:
    event_type: str
    event_id: int
    episode_id: int
    event_name: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    alert_level: Optional[str] = None
    alert_score: Optional[float] = None
    episode_alert_level: Optional[str] = None
    episode_alert_score: Optional[float] = None
    severity_value: Optional[float] = None
    severity_text: Optional[str] = None
    severity_unit: Optional[str] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    date_modified: Optional[datetime] = None
    is_current: bool = False
    is_temporary: bool = False
    country: Optional[str] = None
    iso3: Optional[str] = None
    affected_countries: Optional[list[str]] = None
    glide: Optional[str] = None
    polygon_label: Optional[str] = None
    lon: float = 0.0
    lat: float = 0.0
    footprint_geojson: Optional[dict[str, Any]] = None
    source: Optional[str] = None
    geometry_url: Optional[str] = None
    report_url: Optional[str] = None
    raw_properties: dict[str, Any] = field(default_factory=dict)
    ingestion_source: str = "EVENTS4APP"


@dataclass
class IngestionStats:
    events_fetched: int = 0
    events_upserted: int = 0
    # Always 0 since ingestion went global — kept for the ingestion_runs column
    # and the skip counts recorded by pre-global runs.
    events_skipped: int = 0
    events_failed: int = 0

    def merge(self, other: IngestionStats) -> None:
        self.events_fetched += other.events_fetched
        self.events_upserted += other.events_upserted
        self.events_skipped += other.events_skipped
        self.events_failed += other.events_failed
