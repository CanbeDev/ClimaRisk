from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from app.db.pool import check_db_connection, get_connection
from app.db.repository import HazardRepository
from app.ingestion.backfill import run_backfill
from app.ingestion.polygons import run_polygon_enrichment
from app.ingestion.realtime import run_realtime_poll

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/db")
def health_db() -> dict[str, str]:
    if check_db_connection():
        return {"status": "ok", "database": "connected"}
    raise HTTPException(status_code=503, detail="Database unavailable")


@router.post("/ingest/realtime")
def trigger_realtime() -> dict[str, Any]:
    stats = run_realtime_poll()
    return {
        "job_type": "realtime",
        "events_fetched": stats.events_fetched,
        "events_upserted": stats.events_upserted,
        "events_skipped": stats.events_skipped,
        "events_failed": stats.events_failed,
    }


@router.post("/ingest/backfill")
def trigger_backfill(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
) -> dict[str, Any]:
    stats = run_backfill(from_date=from_date, to_date=to_date)
    return {
        "job_type": "backfill",
        "events_fetched": stats.events_fetched,
        "events_upserted": stats.events_upserted,
        "events_skipped": stats.events_skipped,
        "events_failed": stats.events_failed,
    }


@router.post("/ingest/polygons")
def trigger_polygons(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    stats = run_polygon_enrichment(limit=limit)
    return {
        "job_type": "polygons",
        "events_fetched": stats.events_fetched,
        "events_upserted": stats.events_upserted,
        "events_skipped": stats.events_skipped,
        "events_failed": stats.events_failed,
    }


@router.get("/ingest/runs")
def list_ingestion_runs(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
    with get_connection() as conn:
        repo = HazardRepository(conn)
        runs = repo.list_runs(limit=limit)

    return [
        {
            "id": run.id,
            "job_type": run.job_type,
            "status": run.status,
            "source_endpoint": run.source_endpoint,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "events_fetched": run.events_fetched,
            "events_upserted": run.events_upserted,
            "events_skipped": run.events_skipped,
            "events_failed": run.events_failed,
            "metadata": run.metadata,
        }
        for run in runs
    ]
