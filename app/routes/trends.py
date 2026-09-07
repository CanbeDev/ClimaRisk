from __future__ import annotations

import logging
from typing import Any

import psycopg2
from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.services.trends import run_hazard_trends

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/trends/hazards")
def get_hazard_trends() -> dict[str, Any]:
    """Time-ordered hazard events for the configured country, each with its
    exposure rolled up (asset count, TIV at risk, PML, Protection Gap).

    One list serves both halves of the trend view: frequency / alert-level
    over time is derived from `event_type` + `alert_level` + `from_date`, and
    the financial trend from `tiv_at_risk` / `probable_maximum_loss` /
    `protection_gap` on the same rows. The dataset is a single country's
    event history (tens to low hundreds of rows), so it's returned whole
    rather than pre-binned server-side — the frontend groups by period.
    """
    try:
        points = run_hazard_trends()
    except psycopg2.Error as exc:
        log.exception("Database error building hazard trend series")
        raise HTTPException(
            status_code=500,
            detail="Database error while building hazard trend series",
        ) from exc

    return {
        "country": get_settings().gdacs_country_filter,
        "events": [
            {
                "hazard_event_id": p.hazard_event_id,
                "event_type": p.event_type,
                "event_id": p.event_id,
                "episode_id": p.episode_id,
                "event_name": p.event_name,
                "from_date": p.from_date.isoformat() if p.from_date else None,
                "alert_level": p.alert_level,
                "has_footprint": p.has_footprint,
                "asset_count": p.asset_count,
                "tiv_at_risk": p.tiv_at_risk,
                "damage_ratio": p.damage_ratio,
                "probable_maximum_loss": p.probable_maximum_loss,
                "declared_insured_value": p.declared_insured_value,
                "protection_gap": p.protection_gap,
            }
            for p in points
        ],
    }
