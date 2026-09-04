from __future__ import annotations

import logging
from datetime import date

from app.config import Settings, get_settings
from app.db.pool import get_connection
from app.db.repository import HazardRepository, process_features, resolve_run_status
from app.gdacs.client import GDACSClient
from app.gdacs.models import IngestionStats

log = logging.getLogger(__name__)


def run_realtime_poll(settings: Settings | None = None) -> IngestionStats:
    settings = settings or get_settings()
    stats = IngestionStats()

    with GDACSClient(settings) as client, get_connection() as conn:
        repo = HazardRepository(conn)
        run_id = repo.start_run("realtime", client.settings.gdacs_base_url + "/events/geteventlist/EVENTS4APP")
        try:
            features = client.fetch_events4app()
            stats = process_features(
                repo,
                run_id,
                features,
                country_filter=settings.gdacs_country_filter,
                ingestion_source="EVENTS4APP",
                fetch_polygons=False,
                chunk_size=settings.ingest_commit_chunk_size,
            )
            status = resolve_run_status(stats)
            repo.finish_run(run_id, stats, status)
            log.info(
                "Realtime poll complete: fetched=%d upserted=%d skipped=%d failed=%d",
                stats.events_fetched,
                stats.events_upserted,
                stats.events_skipped,
                stats.events_failed,
            )
        except Exception as exc:
            conn.rollback()
            repo.log_error(run_id, stage="fetch", message=str(exc), error_type=type(exc).__name__)
            repo.finish_run(run_id, stats, "failed")
            raise

    return stats
