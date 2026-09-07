from __future__ import annotations

import logging
from typing import Any

import psycopg2
from fastapi import APIRouter, HTTPException

from app.services.intersection import run_intersection

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/exposure/intersect/{hazard_event_id}")
def get_exposure_intersection(hazard_event_id: int) -> dict[str, Any]:
    try:
        result = run_intersection(hazard_event_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except psycopg2.Error as exc:
        log.exception(
            "Database error computing exposure intersection for hazard_event_id=%s",
            hazard_event_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Database error while computing exposure intersection",
        ) from exc

    return {
        "hazard_event_id": result.hazard_event_id,
        "event_type": result.event_type,
        "event_id": result.event_id,
        "episode_id": result.episode_id,
        "event_name": result.event_name,
        "from_date": result.from_date.isoformat() if result.from_date else None,
        "has_footprint": result.has_footprint,
        "alert_level": result.alert_level,
        "asset_count": result.asset_count,
        "total_insured_value": result.total_insured_value,
        "total_daily_net_revenue": result.total_daily_net_revenue,
        "damage_ratio": result.damage_ratio,
        "probable_maximum_loss": result.probable_maximum_loss,
        "total_declared_insured_value": result.total_declared_insured_value,
        "protection_gap": result.protection_gap,
        "protection_gap_pct": result.protection_gap_pct,
        "assets": [
            {
                "id": asset.id,
                "asset_name": asset.asset_name,
                "asset_type": asset.asset_type,
                "iso3": asset.iso3,
                "building_value": asset.building_value,
                "contents_value": asset.contents_value,
                "total_insured_value": asset.total_insured_value,
                "insured_value": asset.insured_value,
                "daily_net_revenue": asset.daily_net_revenue,
                "variable_cost_ratio": asset.variable_cost_ratio,
                "contribution_margin": asset.contribution_margin,
            }
            for asset in result.assets
        ],
    }
