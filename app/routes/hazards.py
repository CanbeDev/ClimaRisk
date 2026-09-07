from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from app.config import get_settings
from app.db.pool import get_connection

router = APIRouter()


@router.get("/hazards")
def list_hazards() -> dict[str, Any]:
    """Hazard events for the configured country filter, as a GeoJSON FeatureCollection.

    Geometry is the event footprint when one has been fetched (polygon
    enrichment has run for it), otherwise falls back to the point centroid
    so every event is still mappable — `has_footprint` tells the frontend
    which case it's in.
    """
    country = get_settings().gdacs_country_filter
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, event_type, event_id, episode_id, event_name,
                       alert_level, from_date, iso3,
                       ST_AsGeoJSON(COALESCE(footprint, centroid)) AS geometry_json,
                       footprint IS NOT NULL AS has_footprint
                FROM hazard_events
                WHERE iso3 = %s OR %s = ANY(affected_countries)
                ORDER BY from_date DESC NULLS LAST
                """,
                (country, country),
            )
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
