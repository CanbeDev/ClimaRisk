from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from app.db.pool import get_connection

router = APIRouter()


@router.get("/assets")
def list_assets() -> dict[str, Any]:
    """All insured assets as a GeoJSON FeatureCollection, for map markers."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, asset_name, asset_type, iso3,
                       building_value, contents_value, total_insured_value,
                       daily_net_revenue, variable_cost_ratio, insured_value,
                       ST_AsGeoJSON(location) AS geometry_json
                FROM assets
                ORDER BY id
                """
            )
            rows = cur.fetchall()

    features = [
        {
            "type": "Feature",
            "geometry": json.loads(row[10]),
            "properties": {
                "id": row[0],
                "asset_name": row[1],
                "asset_type": row[2],
                "iso3": row[3],
                "building_value": float(row[4]) if row[4] is not None else 0.0,
                "contents_value": float(row[5]) if row[5] is not None else 0.0,
                "total_insured_value": float(row[6]) if row[6] is not None else 0.0,
                "daily_net_revenue": float(row[7]) if row[7] is not None else None,
                "variable_cost_ratio": float(row[8]) if row[8] is not None else None,
                "insured_value": float(row[9]) if row[9] is not None else None,
            },
        }
        for row in rows
    ]

    return {"type": "FeatureCollection", "features": features}
