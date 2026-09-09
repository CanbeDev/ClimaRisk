from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query

from app.config import get_settings
from app.db.pool import get_connection

router = APIRouter()

_SELECT = """
    SELECT id, event_type, event_id, episode_id, event_name,
           alert_level, from_date, iso3,
           ST_AsGeoJSON(COALESCE(footprint, centroid)) AS geometry_json,
           footprint IS NOT NULL AS has_footprint
    FROM hazard_events
"""
# Same country predicate as run_hazard_trends() — the iso3 column OR the
# affected_countries array (regional events list several ISO3 codes).
_COUNTRY_WHERE = "WHERE iso3 = %s OR %s = ANY(affected_countries)"
_ORDER = "ORDER BY from_date DESC NULLS LAST"


@router.get("/hazards")
def list_hazards(scope: str = Query(default="country")) -> dict[str, Any]:
    """Hazard events as a GeoJSON FeatureCollection.

    `hazard_events` is a worldwide table (ingestion stores every GDACS event).
    By default this returns only events affecting the configured country
    (`GDACS_COUNTRY_FILTER`), keeping the Live Map view South-Africa-scoped.
    Pass `?scope=global` to get the full worldwide dataset — the same rows,
    the country filter skipped — for the 3D globe view. No separate endpoint.

    Geometry is the event footprint when polygon enrichment has run for it,
    otherwise the point centroid, so every event is mappable; `has_footprint`
    tells the frontend which case it's in.
    """
    if scope == "global":
        query, params = f"{_SELECT} {_ORDER}", ()
    else:
        country = get_settings().gdacs_country_filter
        query, params = f"{_SELECT} {_COUNTRY_WHERE} {_ORDER}", (country, country)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    features = [
        {
            "type": "Feature",
            "geometry": json.loads(row[8]),
            "properties": {
                "hazard_event_id": row[0],
                "event_type": row[1],
                "event_id": row[2],
                "episode_id": row[3],
                "event_name": row[4],
                "alert_level": row[5],
                "from_date": row[6].isoformat() if row[6] else None,
                "iso3": row[7],
                "has_footprint": row[9],
            },
        }
        for row in rows
    ]

    return {"type": "FeatureCollection", "features": features}
