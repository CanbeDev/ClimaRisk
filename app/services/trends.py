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
from app.services.damage_ratio import compute_pml, get_damage_ratio

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
    avg_proximity_score: float

    @property
    def damage_ratio(self) -> float:
        return get_damage_ratio(self.event_type, self.alert_level, self.avg_proximity_score)

    @property
    def probable_maximum_loss(self) -> float:
        """PML = Exposure at Risk x distance-decay Damage Ratio (Section 4.3),
        via the same `compute_pml()` helper `IntersectionResult` uses — no
        separately hand-written copy of the formula here any more.

        `avg_proximity_score` is this event's TIV-weighted average
        `proximity_score` across its exposed assets (computed in one grouped
        SQL pass in `_TREND_QUERY`, not a per-asset Python loop). Because
        `get_damage_ratio` is *linear* in `proximity_score` and every asset
        behind one event shares the same event_type/alert_level band:

            Σ_i tiv_i * ratio(p_i) = Σ_i tiv_i * (low + (high-low)*p_i)
                                    = TIV_total*low + (high-low) * Σ_i tiv_i*p_i
                                    = TIV_total * (low + (high-low) * avg_p)
                                    = TIV_total * ratio(avg_p)

        — i.e. `compute_pml(tiv_at_risk, ..., avg_proximity_score)` here is
        *exactly* equal to summing each asset's own `compute_pml(...)` the way
        `IntersectionResult.probable_maximum_loss` does, not an approximation
        of it. That equality is what lets this stay one grouped join instead
        of looping `run_intersection()` per event, and is exercised directly
        by `tests/test_disclosure.py::test_disclosure_pml_matches_intersection_service`.
        """
        return compute_pml(self.tiv_at_risk, self.event_type, self.alert_level, self.avg_proximity_score)

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
#
# avg_proximity_score mirrors intersection.py's per-asset proximity_score
# (Step 0) — same centroid/boundary/max-extent formula — but aggregated as a
# single TIV-weighted average per event rather than fetched per asset, so this
# stays the one grouped round trip the module docstring promises (no N+1
# lookups). See HazardTrendPoint.probable_maximum_loss for why that weighted
# average produces an exact, not approximate, PML.
_TREND_QUERY = """
    SELECT h.id, h.event_type, h.event_id, h.episode_id, h.event_name,
           h.from_date, h.alert_level, h.footprint IS NOT NULL AS has_footprint,
           COUNT(a.id) AS asset_count,
           COALESCE(SUM(a.total_insured_value), 0) AS tiv_at_risk,
           COALESCE(SUM(a.insured_value), 0) AS declared_insured_value,
           COALESCE(
               SUM(
                   a.total_insured_value * CASE
                       -- Explicit NULL check, not COALESCE(GREATEST(...), 0.5):
                       -- GREATEST/LEAST ignore NULL arguments rather than
                       -- propagating them, so that form silently resolves to
                       -- 1.0 (not the intended 0.5) for a NULL max_extent
                       -- (GEOMETRYCOLLECTION boundary, or a degenerate
                       -- zero-extent footprint) -- see intersection.py's
                       -- _fetch_intersecting_assets for the same fix.
                       WHEN hz.max_extent IS NULL THEN 0.5
                       ELSE GREATEST(0.0, LEAST(1.0,
                           1.0 - ST_Distance(a.location, hz.centroid) / hz.max_extent
                       ))
                   END
               ) / NULLIF(SUM(a.total_insured_value), 0),
               0
           ) AS avg_proximity_score
    FROM hazard_events h
    LEFT JOIN assets a
        ON h.footprint IS NOT NULL
        AND ST_Intersects(a.location, h.footprint)
    LEFT JOIN LATERAL (
        SELECT ST_Centroid(h.footprint) AS centroid,
               NULLIF(ST_MaxDistance(ST_Centroid(h.footprint), ST_Boundary(h.footprint)), 0) AS max_extent
    ) hz ON true
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
            avg_proximity_score=float(row[11]) if row[11] is not None else 0.0,
        )
        for row in rows
    ]

    log.info("Hazard trend series: %d events", len(points))
    return points


# --------------------------------------------------------------------------- #
# Concentration / accumulation risk (Step 4)
# --------------------------------------------------------------------------- #

# South Africa's mainland bounding box (min_lon, min_lat, max_lon, max_lat).
# Deliberately mainland-only (excludes the Prince Edward Islands, ~1,900km
# southeast) — the asset book this index scores is mainland-only by
# construction, same as every other SA-scoped view in this codebase.
SA_BBOX = (16.0, -35.0, 33.0, -22.0)

# 1 degree (~111km at the equator, ~98km at South Africa's latitude). Chosen
# coarse rather than fine: SA's own historical event count is small (a
# handful of ZAF-tagged events to date, per docs/architecture.md), so a
# finer grid would leave almost every cell's hazard-density score at exactly
# 0 or 1 with nothing in between, and a demo-scale asset book would scatter
# thinly across many singleton cells rather than showing any real
# concentration signal. 1 degree is coarse enough to still get more than a
# handful of events per populated cell, fine enough to keep South Africa's
# major metros (Cape Town, Johannesburg, Durban) in separate cells rather
# than collapsing the whole country into a handful of regions. Worth
# revisiting once real historical volume and a real client portfolio replace
# the current demo-scale data both were chosen against.
GRID_CELL_SIZE_DEGREES = 1.0

# The maximum PML loading a fully-concentrated portfolio (all TIV in the
# single most hazard-dense cell) gets, at weighted_concentration_index == 1.0.
# A documented round-number ceiling in the same spirit as this codebase's
# other placeholder loadings (the HAZUS damage-ratio bands, the compounding
# multiplier) — not a calibrated capital charge. A real accumulation charge
# would come from a catastrophe model's occurrence-exceedance curve, which
# this pipeline doesn't have; 50% is chosen to be large enough to change a
# reader's read of the number when concentration is severe, without dwarfing
# the underlying PML estimate, which is itself already an approximation.
MAX_CONCENTRATION_PENALTY = 0.50


@dataclass
class ConcentrationResult:
    """Portfolio-level (not period-scoped) accumulation-risk summary: how
    much of the insured book's TIV sits in grid cells with a history of
    hazard activity, versus spread across cells with none.

    `weighted_concentration_index` is a Herfindahl-Hirschman-style index over
    each cell's TIV share, weighted by that cell's own hazard-density score:

        index = Σ_cells (tiv_share_i)^2 * density_i

    A plain (unweighted) HHI over TIV share alone would already tell you
    "how concentrated is this book, geographically" — but a book concentrated
    in a cell with zero hazard history is a diversification problem for other
    reasons (a single client, a single asset type), not a *climate*
    accumulation problem, which is specifically what this index is meant to
    price. Multiplying each cell's squared TIV share by its own density
    means TIV sitting in a historically hazard-dense cell contributes fully,
    TIV sitting in a cell with no hazard history contributes nothing (however
    concentrated it is there), and the two effects compound when the same
    cell is both TIV-heavy and hazard-dense — exactly the "high TIV in a
    high-density cell should push the index up" behaviour this was built for.
    Bounded in [0, 1]: 0 when the book is either well-spread or sits entirely
    in hazard-free cells, 1 only when *all* TIV sits in the single cell with
    the highest historical hazard count.
    """

    grid_cell_count: int
    cell_size_degrees: float
    weighted_concentration_index: float

    @property
    def penalty(self) -> float:
        """The PML loading this index implies — see MAX_CONCENTRATION_PENALTY
        for why 50% is the chosen ceiling."""
        return MAX_CONCENTRATION_PENALTY * self.weighted_concentration_index


def compute_concentration_index(settings: Optional[Settings] = None) -> ConcentrationResult:
    """Grid South Africa's bounding box into fixed 1-degree cells, score each
    cell's historical hazard density and the portfolio's TIV share sitting in
    it, and combine them into `ConcentrationResult`.

    **Grid construction.** `generate_series` + `ST_MakeEnvelope` builds the
    grid rather than `ST_SnapToGrid` or `ST_HexagonGrid` (both suggested as
    options for this step): `ST_SnapToGrid` doesn't generate a grid of cells
    at all — it snaps an existing geometry's own vertex coordinates onto a
    grid, a different operation entirely, so it can't build the cell set this
    needs. `ST_HexagonGrid` does generate one, but needs PostGIS 3.1+, which
    this deployment's actual PostGIS version isn't confirmed to be — plain
    `generate_series`/`ST_MakeEnvelope` produces the same fixed-size square
    grid using functions available on every PostGIS version this codebase
    already assumes elsewhere, rather than gating this feature on a version
    bump nothing else here requires.

    **Hazard density** counts, per cell, footprint-bearing events over the
    *entire* ingestion history (not the reporting period — this is a
    portfolio-level figure, recomputed fresh on each call rather than
    period-scoped), normalised against the single highest cell count found
    (1.0 for the most-hit cell, 0.0 for a cell with no history). This one
    query keeps the `iso3`/`affected_countries` scoping every other read
    query in this codebase uses, even though every cell here already sits
    inside the South Africa bounding box by construction — deliberately
    conservative rather than assuming geography alone is an adequate proxy
    for this codebase's usual country scope.

    **TIV share** sums `assets.total_insured_value` per cell against the
    portfolio total (0 for an empty book, not an error).

    A book with zero TIV, or a history with zero ingested hazard events
    anywhere in South Africa, returns `weighted_concentration_index == 0.0`
    (nothing to concentrate, or no signal to weight against) rather than
    dividing by zero.
    """
    settings = settings or get_settings()
    country = settings.gdacs_country_filter
    min_lon, min_lat, max_lon, max_lat = SA_BBOX

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH grid AS (
                    SELECT row_number() OVER () AS cell_id,
                           ST_MakeEnvelope(x, y, x + %(size)s, y + %(size)s, 4326) AS cell
                    FROM generate_series(%(min_lon)s, %(max_lon)s - %(size)s, %(size)s) AS x,
                         generate_series(%(min_lat)s, %(max_lat)s - %(size)s, %(size)s) AS y
                ),
                hazard_counts AS (
                    SELECT g.cell_id, COUNT(h.id) AS hazard_count
                    FROM grid g
                    LEFT JOIN hazard_events h
                        ON h.footprint IS NOT NULL
                       AND ST_Intersects(h.footprint, g.cell)
                       AND (h.iso3 = %(country)s OR %(country)s = ANY(h.affected_countries))
                    GROUP BY g.cell_id
                ),
                asset_tiv AS (
                    SELECT g.cell_id, COALESCE(SUM(a.total_insured_value), 0) AS cell_tiv
                    FROM grid g
                    LEFT JOIN assets a ON ST_Intersects(a.location, g.cell)
                    GROUP BY g.cell_id
                )
                SELECT g.cell_id, hc.hazard_count, at.cell_tiv
                FROM grid g
                JOIN hazard_counts hc ON hc.cell_id = g.cell_id
                JOIN asset_tiv at ON at.cell_id = g.cell_id
                """,
                {
                    "size": GRID_CELL_SIZE_DEGREES,
                    "min_lon": min_lon,
                    "min_lat": min_lat,
                    "max_lon": max_lon,
                    "max_lat": max_lat,
                    "country": country,
                },
            )
            rows = cur.fetchall()

    grid_cell_count = len(rows)
    total_tiv = sum(float(row[2]) for row in rows)
    max_hazard_count = max((row[1] for row in rows), default=0)

    if total_tiv <= 0 or max_hazard_count <= 0:
        log.info(
            "Concentration index: nothing to compute (total_tiv=%.2f, max_hazard_count=%d)",
            total_tiv,
            max_hazard_count,
        )
        return ConcentrationResult(grid_cell_count, GRID_CELL_SIZE_DEGREES, 0.0)

    weighted_index = 0.0
    for _, hazard_count, cell_tiv in rows:
        tiv_share = float(cell_tiv) / total_tiv
        density = hazard_count / max_hazard_count
        weighted_index += (tiv_share**2) * density

    log.info(
        "Concentration index for %s: %d cells, weighted_concentration_index=%.4f",
        country,
        grid_cell_count,
        weighted_index,
    )
    return ConcentrationResult(grid_cell_count, GRID_CELL_SIZE_DEGREES, weighted_index)
