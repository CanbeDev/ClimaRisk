from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg2
from psycopg2.extensions import connection as PgConnection

from app.gdacs.models import HazardEvent, IngestionStats

log = logging.getLogger(__name__)


@dataclass
class IngestionRun:
    id: int
    job_type: str
    status: str
    source_endpoint: Optional[str]
    started_at: datetime
    finished_at: Optional[datetime]
    events_fetched: int
    events_upserted: int
    events_skipped: int
    events_failed: int
    metadata: Optional[dict[str, Any]]


class HazardRepository:
    def __init__(self, conn: PgConnection) -> None:
        self.conn = conn

    def start_run(
        self,
        job_type: str,
        source_endpoint: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_runs (job_type, status, source_endpoint, metadata)
                VALUES (%s, 'running', %s, %s)
                RETURNING id
                """,
                (job_type, source_endpoint, json.dumps(metadata) if metadata else None),
            )
            run_id = cur.fetchone()[0]
        self.conn.commit()
        return run_id

    def finish_run(
        self,
        run_id: int,
        stats: IngestionStats,
        status: str,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingestion_runs
                SET status = %s,
                    finished_at = now(),
                    events_fetched = %s,
                    events_upserted = %s,
                    events_skipped = %s,
                    events_failed = %s
                WHERE id = %s
                """,
                (
                    status,
                    stats.events_fetched,
                    stats.events_upserted,
                    stats.events_skipped,
                    stats.events_failed,
                    run_id,
                ),
            )
        self.conn.commit()

    def log_error(
        self,
        run_id: int,
        *,
        stage: str,
        message: str,
        event_type: Optional[str] = None,
        event_id: Optional[int] = None,
        episode_id: Optional[int] = None,
        error_type: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_errors (
                    run_id, event_type, event_id, episode_id,
                    stage, error_type, message, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    event_type,
                    event_id,
                    episode_id,
                    stage,
                    error_type,
                    message,
                    json.dumps(payload) if payload else None,
                ),
            )

    def upsert_event(self, event: HazardEvent) -> None:
        footprint_geojson = json.dumps(event.footprint_geojson) if event.footprint_geojson else None
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO hazard_events (
                    event_type, event_id, episode_id,
                    event_name, title, description,
                    alert_level, alert_score, episode_alert_level, episode_alert_score,
                    severity_value, severity_text, severity_unit,
                    from_date, to_date, date_modified, is_current, is_temporary,
                    country, iso3, affected_countries, glide, polygon_label,
                    centroid, footprint,
                    source, geometry_url, report_url, raw_properties,
                    ingestion_source, footprint_fetched_at, last_seen_at
                ) VALUES (
                    %(event_type)s, %(event_id)s, %(episode_id)s,
                    %(event_name)s, %(title)s, %(description)s,
                    %(alert_level)s, %(alert_score)s, %(episode_alert_level)s, %(episode_alert_score)s,
                    %(severity_value)s, %(severity_text)s, %(severity_unit)s,
                    %(from_date)s, %(to_date)s, %(date_modified)s, %(is_current)s, %(is_temporary)s,
                    %(country)s, %(iso3)s, %(affected_countries)s, %(glide)s, %(polygon_label)s,
                    ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326),
                    CASE WHEN %(footprint_geojson)s IS NULL THEN NULL
                         ELSE ST_SetSRID(ST_GeomFromGeoJSON(%(footprint_geojson)s), 4326) END,
                    %(source)s, %(geometry_url)s, %(report_url)s, %(raw_properties)s,
                    %(ingestion_source)s,
                    CASE WHEN %(footprint_geojson)s IS NULL THEN NULL ELSE now() END,
                    now()
                )
                ON CONFLICT (event_type, event_id, episode_id) DO UPDATE SET
                    event_name           = EXCLUDED.event_name,
                    title                = EXCLUDED.title,
                    description          = EXCLUDED.description,
                    alert_level          = EXCLUDED.alert_level,
                    alert_score          = EXCLUDED.alert_score,
                    episode_alert_level  = EXCLUDED.episode_alert_level,
                    episode_alert_score  = EXCLUDED.episode_alert_score,
                    severity_value       = EXCLUDED.severity_value,
                    severity_text        = EXCLUDED.severity_text,
                    severity_unit        = EXCLUDED.severity_unit,
                    to_date              = EXCLUDED.to_date,
                    date_modified        = EXCLUDED.date_modified,
                    is_current           = EXCLUDED.is_current,
                    is_temporary         = EXCLUDED.is_temporary,
                    country              = EXCLUDED.country,
                    iso3                 = EXCLUDED.iso3,
                    affected_countries   = EXCLUDED.affected_countries,
                    glide                = EXCLUDED.glide,
                    polygon_label        = EXCLUDED.polygon_label,
                    centroid             = CASE
                        WHEN EXCLUDED.date_modified IS NULL THEN EXCLUDED.centroid
                        WHEN hazard_events.date_modified IS NULL THEN EXCLUDED.centroid
                        WHEN EXCLUDED.date_modified >= hazard_events.date_modified THEN EXCLUDED.centroid
                        ELSE hazard_events.centroid
                    END,
                    footprint            = COALESCE(EXCLUDED.footprint, hazard_events.footprint),
                    footprint_fetched_at = CASE
                        WHEN EXCLUDED.footprint IS NOT NULL THEN now()
                        ELSE hazard_events.footprint_fetched_at
                    END,
                    geometry_url         = COALESCE(EXCLUDED.geometry_url, hazard_events.geometry_url),
                    report_url           = COALESCE(EXCLUDED.report_url, hazard_events.report_url),
                    raw_properties       = EXCLUDED.raw_properties,
                    ingestion_source     = EXCLUDED.ingestion_source,
                    last_seen_at         = now();
                """,
                {
                    "event_type": event.event_type,
                    "event_id": event.event_id,
                    "episode_id": event.episode_id,
                    "event_name": event.event_name,
                    "title": event.title,
                    "description": event.description,
                    "alert_level": event.alert_level,
                    "alert_score": event.alert_score,
                    "episode_alert_level": event.episode_alert_level,
                    "episode_alert_score": event.episode_alert_score,
                    "severity_value": event.severity_value,
                    "severity_text": event.severity_text,
                    "severity_unit": event.severity_unit,
                    "from_date": event.from_date,
                    "to_date": event.to_date,
                    "date_modified": event.date_modified,
                    "is_current": event.is_current,
                    "is_temporary": event.is_temporary,
                    "country": event.country,
                    "iso3": event.iso3,
                    "affected_countries": event.affected_countries,
                    "glide": event.glide,
                    "polygon_label": event.polygon_label,
                    "lon": event.lon,
                    "lat": event.lat,
                    "footprint_geojson": footprint_geojson,
                    "source": event.source,
                    "geometry_url": event.geometry_url,
                    "report_url": event.report_url,
                    "raw_properties": json.dumps(event.raw_properties),
                    "ingestion_source": event.ingestion_source,
                },
            )

    def update_footprint(
        self,
        event_type: str,
        event_id: int,
        episode_id: int,
        footprint_geojson: dict[str, Any],
    ) -> bool:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE hazard_events
                SET footprint = ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
                    footprint_fetched_at = now(),
                    last_seen_at = now()
                WHERE event_type = %s AND event_id = %s AND episode_id = %s
                """,
                (json.dumps(footprint_geojson), event_type, event_id, episode_id),
            )
            updated = cur.rowcount > 0
        return updated

    def fetch_pending_polygons(self, country: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_type, event_id, episode_id, geometry_url
                FROM hazard_events
                WHERE (iso3 = %s OR %s = ANY(affected_countries))
                  AND footprint IS NULL
                  AND geometry_url IS NOT NULL
                ORDER BY last_seen_at DESC
                LIMIT %s
                """,
                (country, country, limit),
            )
            rows = cur.fetchall()
        return [
            {
                "event_type": row[0],
                "event_id": row[1],
                "episode_id": row[2],
                "geometry_url": row[3],
            }
            for row in rows
        ]

    def list_runs(self, limit: int = 20) -> list[IngestionRun]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, job_type, status, source_endpoint, started_at, finished_at,
                       events_fetched, events_upserted, events_skipped, events_failed, metadata
                FROM ingestion_runs
                ORDER BY started_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

        runs: list[IngestionRun] = []
        for row in rows:
            metadata = row[10]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            runs.append(
                IngestionRun(
                    id=row[0],
                    job_type=row[1],
                    status=row[2],
                    source_endpoint=row[3],
                    started_at=row[4],
                    events_fetched=row[6] or 0,
                    events_upserted=row[7] or 0,
                    events_skipped=row[8] or 0,
                    events_failed=row[9] or 0,
                    finished_at=row[5],
                    metadata=metadata,
                )
            )
        return runs


def resolve_run_status(stats: IngestionStats) -> str:
    if stats.events_failed == 0:
        return "success"
    if stats.events_upserted > 0:
        return "partial"
    return "failed"


def process_features(
    repo: HazardRepository,
    run_id: int,
    features: list[dict[str, Any]],
    *,
    country_filter: Optional[str],
    ingestion_source: str,
    fetch_polygons: bool = False,
    client: Any = None,
    chunk_size: int = 20,
) -> IngestionStats:
    stats = IngestionStats(events_fetched=len(features))
    pending_since_commit = 0

    for feature in features:
        props = feature.get("properties") if isinstance(feature, dict) else None

        from app.gdacs.parser import event_affects_country, parse_feature

        country_properties = props if isinstance(props, dict) else {}
        if country_filter and not event_affects_country(country_properties, country_filter):
            stats.events_skipped += 1
            continue

        with repo.conn.cursor() as cur:
            cur.execute("SAVEPOINT event_sp")

        try:
            footprint = None
            if fetch_polygons and client and isinstance(props, dict):
                urls = props.get("url") or {}
                geometry_url = urls.get("geometry") if isinstance(urls, dict) else None
                event_type = props.get("eventtype")
                event_id = props.get("eventid")
                episode_id = props.get("episodeid")
                if event_type and event_id is not None and episode_id is not None:
                    footprint = client.fetch_geometry(
                        event_type=str(event_type),
                        event_id=int(event_id),
                        episode_id=int(episode_id),
                        geometry_url=geometry_url,
                    )
                    client.polite_delay()

            event = parse_feature(
                feature,
                ingestion_source=ingestion_source,
                footprint_geojson=footprint,
            )
            if event is None:
                with repo.conn.cursor() as cur:
                    cur.execute("ROLLBACK TO SAVEPOINT event_sp")
                    cur.execute("RELEASE SAVEPOINT event_sp")
                stats.events_failed += 1
                repo.log_error(
                    run_id,
                    stage="parse",
                    message="Feature could not be parsed",
                    payload=feature if isinstance(feature, dict) else None,
                )
            else:
                repo.upsert_event(event)
                with repo.conn.cursor() as cur:
                    cur.execute("RELEASE SAVEPOINT event_sp")
                stats.events_upserted += 1

            pending_since_commit += 1

        except (psycopg2.Error, ValueError, TypeError) as exc:
            with repo.conn.cursor() as cur:
                cur.execute("ROLLBACK TO SAVEPOINT event_sp")
                cur.execute("RELEASE SAVEPOINT event_sp")
            stats.events_failed += 1
            event_type = props.get("eventtype") if isinstance(props, dict) else None
            event_id = props.get("eventid") if isinstance(props, dict) else None
            episode_id = props.get("episodeid") if isinstance(props, dict) else None
            repo.log_error(
                run_id,
                stage="upsert",
                message=str(exc),
                error_type=type(exc).__name__,
                event_type=str(event_type) if event_type else None,
                event_id=int(event_id) if event_id is not None else None,
                episode_id=int(episode_id) if episode_id is not None else None,
                payload=feature if isinstance(feature, dict) else None,
            )

            pending_since_commit += 1

        if pending_since_commit >= chunk_size:
            repo.conn.commit()
            pending_since_commit = 0

    if pending_since_commit:
        repo.conn.commit()

    return stats
