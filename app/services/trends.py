"""Historical / trend view service (Build Order Step 6).

The exposure dashboard's single-event drill-down lives in
`app/services/intersection.py`; this module answers the other question the
Master Document's trend view asks: *how have hazard frequency, severity, and
insured exposure moved over time?*

It deliberately does **not** loop `run_intersection()` once per event. That
service opens its own connection and is shaped for "one footprint, in detail";
the trend view needs the same TIV / PML / Protection-Gap numbers for *every*
event at once, and a single grouped spatial join delivers them in one round
trip. The per-event financial formulas below are kept identical to
`IntersectionResult` so the two views can never disagree on a number.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.config import Settings, get_settings
from app.db.pool import get_connection
from app.services.damage_ratio import get_damage_ratio

log = logging.getLogger(__name__)


@dataclass
class HazardTrendPoint:
    """One hazard event, with its exposure rolled up to a single row.

    `asset_count` / `tiv_at_risk` / `declared_insured_value` are 0 for an event
    with no footprint yet or no intersecting assets — the same "empty, not an
    error" contract `run_intersection()` gives for a footprint-less event.
    """

    hazard_event_id: int
    event_type: str
    event_id: int
    episode_id: int
    event_name: Optional[str]
    from_date: Optional[datetime]
    alert_level: Optional[str]
    has_footprint: bool
    asset_count: int
    tiv_at_risk: float
    declared_insured_value: float

    @property
    def damage_ratio(self) -> float:
        return get_damage_ratio(self.event_type, self.alert_level)

    @property
    def probable_maximum_loss(self) -> float:
        """PML = Exposure at Risk x Damage Ratio (Section 4.3) — same formula
        as IntersectionResult.probable_maximum_loss."""
        return self.tiv_at_risk * self.damage_ratio

    @property
    def protection_gap(self) -> float:
        """Protection Gap = Exposure at Risk - declared insured value
        (Section 4.5). An asset with no declared `insured_value` counts as
        fully uninsured, matching IntersectionResult."""
        return self.tiv_at_risk - self.declared_insured_value


# One grouped spatial join: every country-relevant event, LEFT JOINed to the
# assets its footprint intersects, so events with no footprint / no exposed
# asset still come back with zeroes rather than dropping out. Country scoping
# mirrors app/routes/hazards.py (iso3 column OR affected_countries array).
_TREND_QUERY = """
    SELECT h.id, h.event_type, h.event_id, h.episode_id, h.event_name,
           h.from_date, h.alert_level, h.footprint IS NOT NULL AS has_footprint,
           COUNT(a.id) AS asset_count,
           COALESCE(SUM(a.total_insured_value), 0) AS tiv_at_risk,
           COALESCE(SUM(a.insured_value), 0) AS declared_insured_value
    FROM hazard_events h
    LEFT JOIN assets a
        ON h.footprint IS NOT NULL
        AND ST_Intersects(a.location, h.footprint)
    WHERE h.iso3 = %s OR %s = ANY(h.affected_countries)
    GROUP BY h.id
    ORDER BY h.from_date ASC NULLS LAST
"""


def run_hazard_trends(settings: Optional[Settings] = None) -> list[HazardTrendPoint]:
    """Every hazard event for the configured country, oldest first, each with
    its exposure (asset count, TIV at risk, declared insured value) rolled up
    from a single grouped spatial join."""
    settings = settings or get_settings()
    country = settings.gdacs_country_filter
    log.info("Building hazard trend series for country=%s", country)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(_TREND_QUERY, (country, country))
            rows = cur.fetchall()

    points = [
        HazardTrendPoint(
            hazard_event_id=row[0],
            event_type=row[1],
            event_id=row[2],
            episode_id=row[3],
            event_name=row[4],
            from_date=row[5],
            alert_level=row[6],
            has_footprint=row[7],
            asset_count=row[8],
            tiv_at_risk=float(row[9]) if row[9] is not None else 0.0,
            declared_insured_value=float(row[10]) if row[10] is not None else 0.0,
        )
        for row in rows
    ]

    log.info("Hazard trend series: %d events", len(points))
    return points
