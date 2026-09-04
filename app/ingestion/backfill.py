from __future__ import annotations

import logging
from datetime import date, timedelta

from app.config import Settings, get_settings
from app.db.pool import get_connection
from app.db.repository import HazardRepository, process_features, resolve_run_status
from app.gdacs.client import GDACSClient, SEARCH_PATH
from app.gdacs.models import IngestionStats

log = logging.getLogger(__name__)


def run_backfill(
    from_date: date | None = None,
    to_date: date | None = None,
    settings: Settings | None = None,
) -> IngestionStats:
    settings = settings or get_settings()
    to_date = to_date or date.today()
    from_date = from_date or (to_date - timedelta(days=365))

    total_stats = IngestionStats()
    page_number = 1

    with GDACSClient(settings) as client, get_connection() as conn:
        repo = HazardRepository(conn)
        run_id = repo.start_run(
            "backfill",
            settings.gdacs_base_url.rstrip("/") + SEARCH_PATH,
            metadata={
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "country": settings.gdacs_country_filter,
            },
        )

        try:
            while True:
                features = client.search_events(
                    from_date=from_date.isoformat(),
                    to_date=to_date.isoformat(),
                    country=settings.gdacs_country_filter,
                    event_list=settings.gdacs_event_types,
                    page_number=page_number,
                )
                if not features:
                    break

                page_stats = process_features(
                    repo,
                    run_id,
                    features,
                    country_filter=settings.gdacs_country_filter,
                    ingestion_source="SEARCH",
                    fetch_polygons=False,
                    chunk_size=settings.ingest_commit_chunk_size,
                )
                total_stats.merge(page_stats)

                if len(features) < 100:
                    break
                page_number += 1

            status = resolve_run_status(total_stats)
            repo.finish_run(run_id, total_stats, status)
            log.info(
                "Backfill complete: pages=%d upserted=%d failed=%d",
                page_number,
                total_stats.events_upserted,
                total_stats.events_failed,
            )
        except Exception as exc:
            conn.rollback()
            repo.log_error(run_id, stage="fetch", message=str(exc), error_type=type(exc).__name__)
            repo.finish_run(run_id, total_stats, "failed")
            raise

    return total_stats
