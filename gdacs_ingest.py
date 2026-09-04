#!/usr/bin/env python3
"""Backward-compatible CLI shim for the ClimRisk GDACS ingestion pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from app.config import get_settings
from app.ingestion.backfill import run_backfill
from app.ingestion.polygons import run_polygon_enrichment
from app.ingestion.realtime import run_realtime_poll

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("gdacs_ingest")


def main() -> int:
    parser = argparse.ArgumentParser(description="GDACS -> PostGIS ingestion (ClimRisk)")
    parser.add_argument(
        "--with-polygons",
        action="store_true",
        help="After ingest, run polygon enrichment for pending ZAF events.",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Run historical SEARCH backfill instead of realtime poll.",
    )
    parser.add_argument("--from-date", type=date.fromisoformat, help="Backfill start date (YYYY-MM-DD)")
    parser.add_argument("--to-date", type=date.fromisoformat, help="Backfill end date (YYYY-MM-DD)")
    args = parser.parse_args()

    settings = get_settings()

    try:
        if args.backfill:
            to_date = args.to_date or date.today()
            from_date = args.from_date or (to_date - timedelta(days=365))
            stats = run_backfill(from_date=from_date, to_date=to_date, settings=settings)
        else:
            stats = run_realtime_poll(settings=settings)

        if args.with_polygons:
            poly_stats = run_polygon_enrichment(settings=settings)
            log.info(
                "Polygon enrichment: updated=%d failed=%d",
                poly_stats.events_upserted,
                poly_stats.events_failed,
            )

        log.info(
            "Ingestion complete: upserted=%d skipped=%d failed=%d",
            stats.events_upserted,
            stats.events_skipped,
            stats.events_failed,
        )
        return 0 if stats.events_failed == 0 else 1
    except Exception as exc:
        log.error("Fatal error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
