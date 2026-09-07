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
from app.services.damage_ratio import get_damage_ratio

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

    @property
    def contribution_margin(self) -> Optional[float]:
        """Daily contribution margin = daily_net_revenue * variable_cost_ratio."""
        if self.daily_net_revenue is None or self.variable_cost_ratio is None:
            return None
        return self.daily_net_revenue * self.variable_cost_ratio


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
    damage_ratio: float = 0.0
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
        """PML = Exposure at Risk x Damage Ratio (Section 4.3)."""
        return self.total_insured_value * self.damage_ratio

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


def _fetch_intersecting_assets(conn, hazard_event_id: int) -> list[ExposedAsset]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.asset_name, a.asset_type, a.iso3,
                   a.building_value, a.contents_value, a.total_insured_value,
                   a.daily_net_revenue, a.variable_cost_ratio, a.insured_value
            FROM assets a
            WHERE ST_Intersects(
                a.location,
                (SELECT footprint FROM hazard_events WHERE id = %s)
            )
            """,
            (hazard_event_id,),
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
            assets = _fetch_intersecting_assets(conn, hazard_event_id)

    result = IntersectionResult(
        hazard_event_id=header["id"],
        event_type=header["event_type"],
        event_id=header["event_id"],
        episode_id=header["episode_id"],
        event_name=header["event_name"],
        from_date=header["from_date"],
        has_footprint=header["has_footprint"],
        alert_level=header["alert_level"],
        damage_ratio=get_damage_ratio(header["event_type"], header["alert_level"]),
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
            f"({asset.asset_type or 'n/a'}) TIV={asset.total_insured_value:,.2f}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
