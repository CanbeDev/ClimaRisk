from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import geopandas as gpd
from shapely import make_valid
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from app.gdacs.models import HazardEvent

log = logging.getLogger(__name__)


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() == "true"


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        log.warning("Could not parse datetime: %s", value)
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def extract_affected_countries(props: dict[str, Any]) -> list[str]:
    """Return every ISO3 country code listed by GDACS for an event."""
    raw = props.get("affectedcountries")
    if not isinstance(raw, list):
        return []

    codes: list[str] = []
    for entry in raw:
        if isinstance(entry, dict):
            code = entry.get("iso3")
        elif isinstance(entry, str):
            code = entry
        else:
            continue

        if code:
            normalized = str(code).strip().upper()
            if normalized and normalized not in codes:
                codes.append(normalized)
    return codes


def event_affects_country(props: dict[str, Any], country_code: str) -> bool:
    """Check both GDACS's primary country and its full affected-country list."""
    target = country_code.strip().upper()
    primary_country = props.get("iso3")
    if isinstance(primary_country, str) and primary_country.strip().upper() == target:
        return True
    return target in extract_affected_countries(props)


def validate_geometry(geojson_geom: dict[str, Any]) -> Optional[dict[str, Any]]:
    try:
        geom: BaseGeometry = shape(geojson_geom)
    except (TypeError, ValueError) as exc:
        log.warning("Invalid geometry: %s", exc)
        return None

    if geom.is_empty:
        return None

    if not geom.is_valid:
        geom = make_valid(geom)
        if geom.is_empty:
            return None

    return mapping(geom)


def geometry_from_feature_collection(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        return None

    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    if gdf.empty:
        return None

    geom = gdf.geometry.iloc[0]
    if geom is None or geom.is_empty:
        return None

    if not geom.is_valid:
        geom = make_valid(geom)

    return mapping(geom)


def parse_feature(
    feature: dict[str, Any],
    *,
    ingestion_source: str = "EVENTS4APP",
    footprint_geojson: Optional[dict[str, Any]] = None,
) -> Optional[HazardEvent]:
    props = feature.get("properties")
    geometry = feature.get("geometry")
    if not isinstance(props, dict) or not isinstance(geometry, dict):
        log.warning("Skipping feature with missing properties or geometry")
        return None

    coords = geometry.get("coordinates")
    if not isinstance(coords, list) or len(coords) < 2:
        log.warning("Skipping feature with invalid centroid coordinates")
        return None

    event_type = props.get("eventtype")
    event_id = props.get("eventid")
    episode_id = props.get("episodeid")
    if not event_type or event_id is None or episode_id is None:
        log.warning("Skipping feature with missing identifiers")
        return None

    severity = props.get("severitydata") or {}
    if not isinstance(severity, dict):
        severity = {}
    urls = props.get("url") or {}
    if not isinstance(urls, dict):
        urls = {}
    affected_countries = extract_affected_countries(props)

    validated_footprint = None
    if footprint_geojson:
        validated_footprint = validate_geometry(footprint_geojson)

    return HazardEvent(
        event_type=str(event_type),
        event_id=int(event_id),
        episode_id=int(episode_id),
        event_name=props.get("eventname") or None,
        title=props.get("name"),
        description=props.get("description"),
        alert_level=props.get("alertlevel"),
        alert_score=_to_float(props.get("alertscore")),
        episode_alert_level=props.get("episodealertlevel"),
        episode_alert_score=_to_float(props.get("episodealertscore")),
        severity_value=_to_float(severity.get("severity")),
        severity_text=severity.get("severitytext"),
        severity_unit=severity.get("severityunit"),
        from_date=parse_datetime(props.get("fromdate")),
        to_date=parse_datetime(props.get("todate")),
        date_modified=parse_datetime(props.get("datemodified")),
        is_current=parse_bool(props.get("iscurrent")),
        is_temporary=parse_bool(props.get("istemporary")),
        country=props.get("country") or None,
        iso3=props.get("iso3") or None,
        affected_countries=affected_countries or None,
        glide=props.get("glide") or None,
        polygon_label=props.get("polygon_label") or props.get("polygonlabel"),
        lon=float(coords[0]),
        lat=float(coords[1]),
        footprint_geojson=validated_footprint,
        source=props.get("source"),
        geometry_url=urls.get("geometry"),
        report_url=urls.get("report"),
        raw_properties=props,
        ingestion_source=ingestion_source,
    )


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def feature_to_json(feature: dict[str, Any]) -> str:
    return json.dumps(feature)
