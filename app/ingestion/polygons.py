from __future__ import annotations

import logging

from app.config import Settings, get_settings
from app.db.pool import get_connection
from app.db.repository import HazardRepository, resolve_run_status
from app.gdacs.client import GDACSClient, GEOMETRY_PATH
from app.gdacs.models import IngestionStats
from app.gdacs.parser import validate_geometry

log = logging.getLogger(__name__)


def run_polygon_enrichment(settings: Settings | None = None, limit: int = 100) -> IngestionStats:
    settings = settings or get_settings()
    stats = IngestionStats()

    with GDACSClient(settings) as client, get_connection() as conn:
        repo = HazardRepository(conn)
        run_id = repo.start_run(
            "polygons",
            settings.gdacs_base_url.rstrip("/") + GEOMETRY_PATH,
        )

        try:
            pending = repo.fetch_pending_polygons(settings.gdacs_country_filter, limit=limit)
            stats.events_fetched = len(pending)

            for row in pending:
                try:
                    geometry = client.fetch_geometry(
                        event_type=row["event_type"],
                        event_id=row["event_id"],
                        episode_id=row["episode_id"],
                        geometry_url=row["geometry_url"],
                    )
                    client.polite_delay()

                    if not geometry:
                        stats.events_failed += 1
                        repo.log_error(
                            run_id,
                            stage="polygon",
                            message="No geometry returned",
                            event_type=row["event_type"],
                            event_id=row["event_id"],
                            episode_id=row["episode_id"],
                        )
                        conn.commit()
                        continue

                    validated = validate_geometry(geometry)
                    if not validated:
                        stats.events_failed += 1
                        repo.log_error(
                            run_id,
                            stage="polygon",
                            message="Geometry validation failed",
                            event_type=row["event_type"],
                            event_id=row["event_id"],
                            episode_id=row["episode_id"],
                        )
                        conn.commit()
                        continue

                    if repo.update_footprint(
                        row["event_type"],
                        row["event_id"],
                        row["episode_id"],
                        validated,
                    ):
                        stats.events_upserted += 1
                    else:
                        stats.events_failed += 1
                        repo.log_error(
                            run_id,
                            stage="polygon",
                            message="Event row not found for footprint update",
                            event_type=row["event_type"],
                            event_id=row["event_id"],
                            episode_id=row["episode_id"],
                        )

                    conn.commit()

                except Exception as exc:
                    stats.events_failed += 1
                    conn.rollback()
                    repo.log_error(
                        run_id,
                        stage="polygon",
                        message=str(exc),
                        error_type=type(exc).__name__,
                        event_type=row["event_type"],
                        event_id=row["event_id"],
                        episode_id=row["episode_id"],
                    )
                    conn.commit()

            status = resolve_run_status(stats)
            repo.finish_run(run_id, stats, status)
            log.info(
                "Polygon enrichment complete: fetched=%d updated=%d failed=%d",
                stats.events_fetched,
                stats.events_upserted,
                stats.events_failed,
            )
        except Exception as exc:
            conn.rollback()
            repo.log_error(run_id, stage="fetch", message=str(exc), error_type=type(exc).__name__)
            repo.finish_run(run_id, stats, "failed")
            raise

    return stats
