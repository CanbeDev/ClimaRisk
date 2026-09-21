"""Spatial intersection service: hazard footprint -> exposed assets (Step 3).

Given a hazard_events row, finds every asset whose location intersects that
event's footprint and totals their exposure. This is the load-bearing query
the exposure dashboard sits on top of.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.config import Settings, get_settings
from app.db.pool import get_connection
from app.services.compounding import COMPOUND_WINDOW_DAYS, compound_multiplier
from app.services.damage_ratio import compute_pml, get_damage_ratio

log = logging.getLogger(__name__)


@dataclass
class ExposedAsset:
    id: int
    asset_name: Optional[str]
    asset_type: Optional[str]
    iso3: Optional[str]
    building_value: float
    contents_value: float
    total_insured_value: float
    daily_net_revenue: Optional[float]
    variable_cost_ratio: Optional[float]
    insured_value: Optional[float]
    # Distance geometry (Step 0), relative to the one footprint this asset was
    # matched against — see _fetch_intersecting_assets for how both are derived
    # from the same GiST-bound subquery, no second spatial pass.
    distance_to_edge: float
    proximity_score: float
    # Multi-hazard compounding (Step 3): 1.0 for an asset with no prior hit
    # inside COMPOUND_WINDOW_DAYS before this event; > 1.0 (compounded) when
    # this same asset was already hit by another footprint-bearing event in
    # that window. Per-asset, not per-event — a sibling asset in the same
    # footprint can be a first-time hit while this one compounds.
    compound_multiplier: float
    is_compound_loss: bool
    # The hazard this asset was intersected against — carried per-asset (not
    # just on the parent IntersectionResult) so damage_ratio/probable_maximum_loss
    # below are self-contained: each asset's ratio depends on its own
    # proximity_score, so it can differ from a sibling asset hit by the same
    # event.
    event_type: str
    alert_level: Optional[str]

    @property
    def contribution_margin(self) -> Optional[float]:
        """Daily contribution margin = daily_net_revenue * variable_cost_ratio."""
        if self.daily_net_revenue is None or self.variable_cost_ratio is None:
            return None
        return self.daily_net_revenue * self.variable_cost_ratio

    @property
    def damage_ratio(self) -> float:
        """This asset's own fully-adjusted ratio: distance-decay (Section 4.3,
        Step 1) interpolated from its own `proximity_score`, then Step 3's
        compounding multiplier layered on top and capped at 1.0 — so two
        assets exposed to the same event can carry different ratios both from
        where they sit *and* from whether either has been hit before."""
        base = get_damage_ratio(self.event_type, self.alert_level, self.proximity_score)
        return min(1.0, base * self.compound_multiplier)

    @property
    def probable_maximum_loss(self) -> float:
        """TIV x this asset's own (distance-decay + compounding) ratio —
        deliberately *not* `compute_pml()` directly, since that shared helper
        (also used by trends.py, which has no per-asset compounding data) only
        knows about distance decay. Compounding is layered on here, at the
        one place that has the per-asset history to know about it."""
        return self.total_insured_value * self.damage_ratio


@dataclass
class IntersectionResult:
    hazard_event_id: int
    event_type: str
    event_id: int
    episode_id: int
    event_name: Optional[str]
    from_date: Optional[datetime]
    has_footprint: bool
    alert_level: Optional[str] = None
    assets: list[ExposedAsset] = field(default_factory=list)

    @property
    def asset_count(self) -> int:
        return len(self.assets)

    @property
    def total_insured_value(self) -> float:
        """Sum of TIV (building + contents) across exposed assets — the Exposure
        at Risk figure (Master Document Section 4.2): the ceiling, not what's
        actually declared as insured."""
        return sum(a.total_insured_value for a in self.assets)

    @property
    def total_daily_net_revenue(self) -> float:
        return sum(a.daily_net_revenue or 0.0 for a in self.assets)

    @property
    def probable_maximum_loss(self) -> float:
        """PML = Σ each exposed asset's own PML (Section 4.3), each computed
        with that asset's distance-decay ratio — not TIV x one event-wide
        ratio, since Step 1 made the ratio position-dependent."""
        return sum(a.probable_maximum_loss for a in self.assets)

    @property
    def damage_ratio(self) -> float:
        """TIV-weighted *effective* ratio implied by probable_maximum_loss —
        kept so `probable_maximum_loss == total_insured_value * damage_ratio`
        still holds as a whole-event figure, even though the real, position-
        dependent ratio now varies per asset (see ExposedAsset.damage_ratio).
        0.0 when there's no exposure to weight, matching the "empty, not an
        error" contract elsewhere on this result."""
        tiv = self.total_insured_value
        return self.probable_maximum_loss / tiv if tiv > 0 else 0.0

    @property
    def total_declared_insured_value(self) -> float:
        """Sum of each exposed asset's declared insured_value. An asset with no
        declared value is treated as fully uninsured (0), not as "unknown and
        excluded" — a deliberate, conservative default that keeps the
        Protection Gap from understating risk just because coverage wasn't
        declared."""
        return sum(a.insured_value or 0.0 for a in self.assets)

    @property
    def protection_gap(self) -> float:
        """Protection Gap = Total Economic Exposure - Insured Value (Section 4.5)."""
        return self.total_insured_value - self.total_declared_insured_value

    @property
    def protection_gap_pct(self) -> Optional[float]:
        """None (not 0) when there's no exposure to divide by — a hazard with
        zero exposed value has an undefined gap percentage, not a 0% gap."""
        if self.total_insured_value <= 0:
            return None
        return self.protection_gap / self.total_insured_value


def _fetch_hazard_header(conn, hazard_event_id: int) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, event_type, event_id, episode_id, event_name, from_date,
                   footprint IS NOT NULL AS has_footprint, alert_level
            FROM hazard_events
            WHERE id = %s
            """,
            (hazard_event_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "event_type": row[1],
        "event_id": row[2],
        "episode_id": row[3],
        "event_name": row[4],
        "from_date": row[5],
        "has_footprint": row[6],
        "alert_level": row[7],
    }


def _fetch_intersecting_assets(
    conn,
    hazard_event_id: int,
    event_type: str,
    alert_level: Optional[str],
) -> list[ExposedAsset]:
    """Assets intersecting one hazard's footprint, plus (Step 0) each asset's
    distance geometry relative to that same footprint:

      * `distance_to_edge` — ST_Distance in metres (::geography, so it's a
        real-world figure) between the asset and the footprint's boundary,
        negated for an asset strictly inside (ST_Contains) so "inside" reads
        as negative/zero and there is no positive case here — every row in
        this result already passed ST_Intersects, so "outside" never occurs.
      * `proximity_score` — 1.0 at the footprint's centroid, 0.0 at its edge,
        radius-normalised against the centroid's farthest boundary point
        (`ST_MaxDistance`). Computed in plain (SRID 4326) geometry space, not
        ::geography — ST_MaxDistance has no geography variant, but since this
        is a ratio of two distances measured the same way, the degree-based
        unit cancels out; that stops being a fair approximation only for a
        footprint spanning a large share of the globe, which a single hazard
        event's polygon does not. GEOMETRYCOLLECTION footprints (a possible
        `make_valid()` repair output) leave ST_Boundary undefined, so this
        COALESCEs to a neutral 0.5 rather than failing the whole request.

    A third figure, `prior_hit_count` (Step 3), counts — for each of these
    same assets — how many *other* footprint-bearing events already
    intersected that specific asset within `COMPOUND_WINDOW_DAYS` before this
    event's `from_date`. It's a correlated subquery per asset row rather than
    a second round trip: the asset set here is already small (one footprint's
    worth), and computing it in Python would mean re-fetching every other
    candidate event's footprint anyway. A NULL `from_date` on this event (no
    anchor for "before") yields 0 prior hits rather than erroring.

    All three ride on the same GiST-bound subquery `assets vs. this one
    footprint` the intersection itself already uses (via the `hz` CTE below,
    which the planner treats as the same single bound geometry as the old
    scalar subquery) — no second spatial pass, no new index.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH hz0 AS (
                SELECT footprint, from_date,
                       ST_Centroid(footprint) AS centroid,
                       ST_Boundary(footprint) AS boundary
                FROM hazard_events WHERE id = %s
            ),
            hz AS (
                SELECT footprint, from_date, centroid, boundary,
                       NULLIF(ST_MaxDistance(centroid, boundary), 0) AS max_extent
                FROM hz0
            )
            SELECT a.id, a.asset_name, a.asset_type, a.iso3,
                   a.building_value, a.contents_value, a.total_insured_value,
                   a.daily_net_revenue, a.variable_cost_ratio, a.insured_value,
                   (CASE WHEN ST_Contains(hz.footprint, a.location) THEN -1 ELSE 1 END)
                       * COALESCE(ST_Distance(a.location::geography, hz.boundary::geography), 0)
                       AS distance_to_edge,
                   -- NB: this must be an explicit NULL check, not
                   -- COALESCE(GREATEST(...), 0.5) -- GREATEST/LEAST ignore
                   -- NULL arguments rather than propagating them, so that
                   -- form silently resolves to 1.0 for a NULL max_extent
                   -- (GEOMETRYCOLLECTION boundary, or a degenerate
                   -- zero-extent footprint) and the 0.5 fallback never fires.
                   CASE
                       WHEN hz.max_extent IS NULL THEN 0.5
                       ELSE GREATEST(0.0, LEAST(1.0,
                           1.0 - ST_Distance(a.location, hz.centroid) / hz.max_extent
                       ))
                   END AS proximity_score,
                   (
                       CASE WHEN hz.from_date IS NULL THEN 0 ELSE (
                           SELECT COUNT(*) FROM hazard_events h2
                           WHERE h2.id != %s
                             AND h2.footprint IS NOT NULL
                             AND ST_Intersects(a.location, h2.footprint)
                             AND h2.from_date >= hz.from_date - (%s * INTERVAL '1 day')
                             AND h2.from_date < hz.from_date
                       ) END
                   ) AS prior_hit_count
            FROM assets a, hz
            WHERE ST_Intersects(a.location, hz.footprint)
            """,
            (hazard_event_id, hazard_event_id, COMPOUND_WINDOW_DAYS),
        )
        rows = cur.fetchall()

    return [
        ExposedAsset(
            id=row[0],
            asset_name=row[1],
            asset_type=row[2],
            iso3=row[3],
            building_value=float(row[4]) if row[4] is not None else 0.0,
            contents_value=float(row[5]) if row[5] is not None else 0.0,
            total_insured_value=float(row[6]) if row[6] is not None else 0.0,
            daily_net_revenue=float(row[7]) if row[7] is not None else None,
            variable_cost_ratio=float(row[8]) if row[8] is not None else None,
            insured_value=float(row[9]) if row[9] is not None else None,
            distance_to_edge=float(row[10]) if row[10] is not None else 0.0,
            proximity_score=float(row[11]) if row[11] is not None else 0.5,
            compound_multiplier=compound_multiplier(row[12] or 0),
            is_compound_loss=bool(row[12]) and row[12] > 0,
            event_type=event_type,
            alert_level=alert_level,
        )
        for row in rows
    ]


def run_intersection(
    hazard_event_id: int,
    settings: Optional[Settings] = None,
) -> IntersectionResult:
    """Find every asset whose location intersects a hazard event's footprint.

    `hazard_event_id` is hazard_events.id (the internal surrogate key), not
    GDACS's own event_id — a single GDACS event_id can have multiple episode
    rows over time, each with its own footprint, so the surrogate key is the
    only unambiguous way to name "one footprint" here.
    """
    settings = settings or get_settings()
    log.info("Running spatial intersection for hazard_events.id=%s", hazard_event_id)

    with get_connection() as conn:
        header = _fetch_hazard_header(conn, hazard_event_id)
        if header is None:
            raise ValueError(f"No hazard_events row with id={hazard_event_id}")

        if not header["has_footprint"]:
            log.warning(
                "hazard_events.id=%s (%s/%s) has no footprint yet — run polygon "
                "enrichment before intersecting (see app/ingestion/polygons.py)",
                hazard_event_id,
                header["event_type"],
                header["event_id"],
            )
            assets: list[ExposedAsset] = []
        else:
            assets = _fetch_intersecting_assets(
                conn, hazard_event_id, header["event_type"], header["alert_level"]
            )

    result = IntersectionResult(
        hazard_event_id=header["id"],
        event_type=header["event_type"],
        event_id=header["event_id"],
        episode_id=header["episode_id"],
        event_name=header["event_name"],
        from_date=header["from_date"],
        has_footprint=header["has_footprint"],
        alert_level=header["alert_level"],
        assets=assets,
    )

    log.info(
        "Intersection complete: hazard_events.id=%s assets=%d total_insured_value=%.2f "
        "damage_ratio=%.2f pml=%.2f protection_gap=%.2f",
        hazard_event_id,
        result.asset_count,
        result.total_insured_value,
        result.damage_ratio,
        result.probable_maximum_loss,
        result.protection_gap,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Spatial intersection: hazard footprint vs. asset exposure"
    )
    parser.add_argument(
        "hazard_event_id",
        type=int,
        help="hazard_events.id (internal surrogate key) to intersect against",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    try:
        result = run_intersection(args.hazard_event_id)
    except ValueError as exc:
        log.error(str(exc))
        return 1

    print(
        f"Hazard event: {result.event_type} {result.event_id} "
        f"(episode {result.episode_id}) — {result.event_name or '(unnamed)'}"
    )
    if not result.has_footprint:
        print("No footprint stored for this event — run polygon enrichment first.")
        return 0

    print(f"Assets intersecting footprint: {result.asset_count}")
    print(f"Total insured value exposed (TIV):   {result.total_insured_value:,.2f}")
    print(f"Damage ratio (alert_level={result.alert_level}): {result.damage_ratio:.0%}")
    print(f"Probable Maximum Loss (PML):    {result.probable_maximum_loss:,.2f}")
    print(f"Declared insured value:         {result.total_declared_insured_value:,.2f}")
    gap_pct = f"{result.protection_gap_pct:.0%}" if result.protection_gap_pct is not None else "n/a"
    print(f"Protection gap:                 {result.protection_gap:,.2f} ({gap_pct})")
    print(f"Total daily net revenue exposed: {result.total_daily_net_revenue:,.2f}")
    for asset in result.assets:
        print(
            f"  - [{asset.id}] {asset.asset_name or '(unnamed)'} "
            f"({asset.asset_type or 'n/a'}) TIV={asset.total_insured_value:,.2f} "
            f"proximity={asset.proximity_score:.2f} ratio={asset.damage_ratio:.0%}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
