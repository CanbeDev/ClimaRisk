from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.ingestion.backfill import run_backfill
from app.ingestion.polygons import run_polygon_enrichment
from app.ingestion.realtime import run_realtime_poll

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _safe_realtime() -> None:
    try:
        run_realtime_poll()
    except Exception:
        log.exception("Scheduled realtime poll failed")


def _safe_polygons() -> None:
    try:
        run_polygon_enrichment()
    except Exception:
        log.exception("Scheduled polygon enrichment failed")


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    settings = get_settings()
    _scheduler = BackgroundScheduler()

    if settings.scheduler_enabled:
        _scheduler.add_job(
            _safe_realtime,
            trigger=IntervalTrigger(hours=settings.gdacs_poll_interval_hours),
            id="realtime_poll",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _scheduler.add_job(
            _safe_polygons,
            trigger=IntervalTrigger(hours=settings.gdacs_polygon_interval_hours),
            id="polygon_enrich",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    _scheduler.start()
    log.info(
        "Scheduler started (realtime=%sh, polygons=%sh)",
        settings.gdacs_poll_interval_hours,
        settings.gdacs_polygon_interval_hours,
    )
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("Scheduler stopped")
