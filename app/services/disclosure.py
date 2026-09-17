"""Climate disclosure report (Build Order Step 8 / Phase 3).

Assembles one TCFD-style report for a reporting period out of the pieces the
rest of the system already computes — the trend service's per-event exposure,
the parametric engine's payout position, and a couple of portfolio roll-up
queries — and can render it as a self-contained, print-to-PDF HTML document.

Two deliberate choices:

  * **No template engine.** It's one report; `render_html()` is a plain
    function building a string, in keeping with the "hand-written SQL, no ORM"
    line elsewhere. Every interpolated value goes through `esc()` or a numeric
    formatter.
  * **Aggregates are stated, not smoothed.** Summing TIV-at-risk across events
    double-counts an asset hit by two hazards, so the report shows the
    per-event table *and* a separate "distinct assets exposed in the period"
    union figure, and labels the naive gross total as such — a disclosure
    report has to be honest about its own arithmetic.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from app.config import Settings, get_settings
from app.db.pool import get_connection
from app.services.compounding import COMPOUND_WINDOW_DAYS
from app.services.intersection import run_intersection
from app.services.parametric import summary as parametric_summary
from app.services.trends import (
    GRID_CELL_SIZE_DEGREES,
    MAX_CONCENTRATION_PENALTY,
    ConcentrationResult,
    HazardTrendPoint,
    compute_concentration_index,
    run_hazard_trends,
)

log = logging.getLogger(__name__)


@dataclass
class AssetTypeBreakdown:
    asset_type: str
    count: int
    total_insured_value: float


@dataclass
class DisclosureReport:
    org_name: str
    iso3: str
    generated_at: datetime
    period_start: date
    period_end: date

    # Portfolio (whole book, not period-scoped)
    asset_count: int
    portfolio_tiv: float
    portfolio_declared_insured_value: float
    assets_by_type: list[AssetTypeBreakdown] = field(default_factory=list)

    # Hazard exposure within the period
    events: list[HazardTrendPoint] = field(default_factory=list)
    distinct_assets_exposed: int = 0
    distinct_tiv_exposed: float = 0.0

    # Step 3: Σ PML contributed by assets already hit by another
    # footprint-bearing event within the compounding window, across every
    # event in the period. Computed eagerly in build_disclosure_report() (it
    # needs per-asset detail run_hazard_trends()'s grouped join doesn't carry),
    # not a lazy property like the other aggregates below.
    compound_pml_contribution: float = 0.0

    # Step 4: portfolio-level (not period-scoped) accumulation-risk summary —
    # see app/services/trends.py:ConcentrationResult for the grid/index derivation.
    concentration: ConcentrationResult = field(
        default_factory=lambda: ConcentrationResult(0, 0.0, 0.0)
    )

    # Parametric position (current, not period-scoped — it's a live ledger)
    parametric: dict = field(default_factory=dict)

    # --- derived -------------------------------------------------------- #

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def firing_events(self) -> list[HazardTrendPoint]:
        return [e for e in self.events if e.asset_count > 0]

    @property
    def gross_tiv_at_risk(self) -> float:
        """Naive Σ across events — double-counts assets hit by more than one
        hazard. Reported next to `distinct_tiv_exposed`, labelled as gross."""
        return sum(e.tiv_at_risk for e in self.events)

    @property
    def gross_pml(self) -> float:
        return sum(e.probable_maximum_loss for e in self.events)

    @property
    def compound_pml_pct(self) -> Optional[float]:
        """Share of gross period PML attributable to assets already hit by
        another event within the compounding window (Step 3,
        app/services/compounding.py) — computed against `gross_pml`, the
        same (non-deduplicated) denominator this report already uses for its
        other "share of period PML" figures, for consistency with them.
        None when there's no PML to divide by, not a fabricated 0 — the same
        "undefined, not zero" contract `protection_gap_pct` and
        `vertical_basis_risk_pct` already use elsewhere."""
        total = self.gross_pml
        if total <= 0:
            return None
        return self.compound_pml_contribution / total

    @property
    def diversification_adjusted_pml(self) -> float:
        """gross_pml loaded up by the portfolio's concentration-in-hazard-
        dense-cells penalty (Step 4) — an adjustment layered *on top of*
        gross_pml, not a replacement for it, `distinct_tiv_exposed`, or any
        other PML figure already on this report: all of them stay visible
        side by side, labelled, the same "state the method, don't just show
        one flattering number" pattern this report already uses for gross vs.
        distinct exposure."""
        return self.gross_pml * (1 + self.concentration.penalty)

    @property
    def peak_event_pml(self) -> Optional[HazardTrendPoint]:
        firing = [e for e in self.events if e.probable_maximum_loss > 0]
        return max(firing, key=lambda e: e.probable_maximum_loss) if firing else None

    @property
    def protection_gap_on_distinct(self) -> float:
        """Gap on the de-duplicated exposed book: distinct TIV exposed minus
        the declared insured value of those same assets is not cheaply
        available, so this uses the portfolio-wide declared ratio as a
        stated approximation."""
        if self.portfolio_tiv <= 0:
            return self.distinct_tiv_exposed
        covered_ratio = self.portfolio_declared_insured_value / self.portfolio_tiv
        return self.distinct_tiv_exposed * (1 - covered_ratio)

    def to_dict(self) -> dict:
        return {
            "org_name": self.org_name,
            "iso3": self.iso3,
            "generated_at": self.generated_at.isoformat(),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "portfolio": {
                "asset_count": self.asset_count,
                "total_insured_value": self.portfolio_tiv,
                "declared_insured_value": self.portfolio_declared_insured_value,
                "by_type": [
                    {
                        "asset_type": b.asset_type,
                        "count": b.count,
                        "total_insured_value": b.total_insured_value,
                    }
                    for b in self.assets_by_type
                ],
            },
            "hazard_exposure": {
                "event_count": self.event_count,
                "events_with_exposed_assets": len(self.firing_events),
                "distinct_assets_exposed": self.distinct_assets_exposed,
                "distinct_tiv_exposed": self.distinct_tiv_exposed,
                "gross_tiv_at_risk": self.gross_tiv_at_risk,
                "gross_probable_maximum_loss": self.gross_pml,
                "protection_gap_on_distinct_exposed": self.protection_gap_on_distinct,
                "compound_pml_contribution": self.compound_pml_contribution,
                "compound_pml_pct": self.compound_pml_pct,
                "concentration_index": self.concentration.weighted_concentration_index,
                "concentration_penalty": self.concentration.penalty,
                "diversification_adjusted_pml": self.diversification_adjusted_pml,
                "peak_event": (
                    {
                        "hazard_event_id": self.peak_event_pml.hazard_event_id,
                        "event_type": self.peak_event_pml.event_type,
                        "event_name": self.peak_event_pml.event_name,
                        "from_date": self.peak_event_pml.from_date.isoformat()
                        if self.peak_event_pml.from_date
                        else None,
                        "probable_maximum_loss": self.peak_event_pml.probable_maximum_loss,
                    }
                    if self.peak_event_pml
                    else None
                ),
                "events": [
                    {
                        "hazard_event_id": e.hazard_event_id,
                        "event_type": e.event_type,
                        "event_id": e.event_id,
                        "episode_id": e.episode_id,
                        "event_name": e.event_name,
                        "from_date": e.from_date.isoformat() if e.from_date else None,
                        "alert_level": e.alert_level,
                        "asset_count": e.asset_count,
                        "tiv_at_risk": e.tiv_at_risk,
                        "damage_ratio": e.damage_ratio,
                        "probable_maximum_loss": e.probable_maximum_loss,
                        "protection_gap": e.protection_gap,
                    }
                    for e in self.events
                ],
            },
            "parametric_position": self.parametric,
        }


_PORTFOLIO_SQL = """
    SELECT COUNT(*),
           COALESCE(SUM(total_insured_value), 0),
           COALESCE(SUM(insured_value), 0)
    FROM assets
"""

_BY_TYPE_SQL = """
    SELECT COALESCE(NULLIF(asset_type, ''), 'unclassified') AS t,
           COUNT(*), COALESCE(SUM(total_insured_value), 0)
    FROM assets
    GROUP BY t
    ORDER BY 3 DESC
"""

# Distinct assets whose footprint-bearing hazards fall inside the reporting
# period — de-duplicated so an asset hit by several events is counted once.
_DISTINCT_EXPOSED_SQL = """
    SELECT COUNT(*), COALESCE(SUM(tiv), 0)
    FROM (
        SELECT DISTINCT a.id, a.total_insured_value AS tiv
        FROM assets a
        JOIN hazard_events h
          ON h.footprint IS NOT NULL
         AND ST_Intersects(a.location, h.footprint)
        WHERE (h.iso3 = %s OR %s = ANY(h.affected_countries))
          AND h.from_date >= %s AND h.from_date < (%s::date + 1)
    ) x
"""

_EVENT_RANGE_SQL = """
    SELECT MIN(from_date)::date, MAX(from_date)::date
    FROM hazard_events
    WHERE iso3 = %s OR %s = ANY(affected_countries)
"""


def build_disclosure_report(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    settings: Optional[Settings] = None,
) -> DisclosureReport:
    settings = settings or get_settings()
    country = settings.gdacs_country_filter

    with get_connection() as conn:
        with conn.cursor() as cur:
            if period_start is None or period_end is None:
                cur.execute(_EVENT_RANGE_SQL, (country, country))
                lo, hi = cur.fetchone()
                period_start = period_start or lo or date(date.today().year, 1, 1)
                period_end = period_end or date.today()
                if hi and hi > period_end:
                    period_end = hi

            cur.execute(_PORTFOLIO_SQL)
            asset_count, portfolio_tiv, portfolio_declared = cur.fetchone()

            cur.execute(_BY_TYPE_SQL)
            by_type = [
                AssetTypeBreakdown(row[0], row[1], float(row[2])) for row in cur.fetchall()
            ]

            cur.execute(
                _DISTINCT_EXPOSED_SQL, (country, country, period_start, period_end)
            )
            distinct_count, distinct_tiv = cur.fetchone()

    all_events = run_hazard_trends(settings=settings)
    events = [
        e
        for e in all_events
        if e.from_date is not None and period_start <= e.from_date.date() <= period_end
    ]

    # Step 3's compound-exposure aggregate needs per-asset detail
    # run_hazard_trends()'s grouped join doesn't carry (compounding is a
    # property of one specific asset's hit history, not something a GROUP BY
    # over the whole period can cheaply reproduce without re-deriving
    # intersection.py's per-asset logic as one much heavier query). Looping
    # run_intersection() per period event is the one deliberate exception to
    # this codebase's "no N+1" rule for hazard-event queries: a disclosure
    # report is a periodic, non-interactive document already assembled from
    # several separate queries, not a per-request dashboard load, so trading
    # a few extra round trips for reusing an already-correct function is the
    # better trade than a second, parallel compounding implementation in SQL.
    compound_pml_contribution = 0.0
    for e in events:
        if e.asset_count == 0:
            continue
        event_intersection = run_intersection(e.hazard_event_id, settings=settings)
        compound_pml_contribution += sum(
            a.probable_maximum_loss for a in event_intersection.assets if a.is_compound_loss
        )

    concentration = compute_concentration_index(settings=settings)

    report = DisclosureReport(
        org_name=settings.report_org_name,
        iso3=country,
        generated_at=datetime.now(timezone.utc),
        period_start=period_start,
        period_end=period_end,
        asset_count=asset_count,
        portfolio_tiv=float(portfolio_tiv),
        portfolio_declared_insured_value=float(portfolio_declared),
        assets_by_type=by_type,
        events=events,
        distinct_assets_exposed=distinct_count,
        distinct_tiv_exposed=float(distinct_tiv),
        compound_pml_contribution=compound_pml_contribution,
        concentration=concentration,
        parametric=parametric_summary(),
    )
    log.info(
        "Built disclosure report: %s..%s, %d events, %d distinct assets exposed",
        period_start,
        period_end,
        report.event_count,
        report.distinct_assets_exposed,
    )
    return report


# --------------------------------------------------------------------------- #
# HTML rendering (no template engine)
# --------------------------------------------------------------------------- #

def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _zar(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"R{value:,.0f}"


def _pct(value: Optional[float]) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


_ALERT_BADGE = {"Red": "#f43f5e", "Orange": "#f59e0b", "Green": "#22c55e"}

_METHODOLOGY = [
    (
        "Damage ratio / PML",
        "Probable Maximum Loss is Exposure-at-Risk × a HAZUS-MH / FEMA depth-damage band "
        "midpoint selected by GDACS alert level (Green/Orange/Red), not hazard-specific "
        "severity (flood depth, cyclone category). It is a screening estimate, not a "
        "calibrated vulnerability model.",
    ),
    (
        "Protection gap",
        "Gap figures treat an asset with no declared insured value as fully uninsured. The "
        "period gap uses the portfolio-wide declared-cover ratio applied to the distinct "
        "exposed book, and is stated as an approximation.",
    ),
    (
        "Parametric basis risk",
        "Basis risk is the parametric payout minus the modelled PML above — there is no "
        "ground-truth loss feed to calibrate against.",
    ),
    (
        "Compound exposure",
        f"An asset already hit by another footprint-bearing event within the last "
        f"{COMPOUND_WINDOW_DAYS} days gets a compounding multiplier on its damage "
        "ratio for this event (capped at 100% of TIV) — a documented placeholder "
        "escalation, not a calibrated recovery curve per asset type or hazard. The "
        "percentage above is gross PML from compound-loss assets over gross period "
        "PML, using the same non-deduplicated denominator as the other gross "
        "figures on this page.",
    ),
    (
        "Concentration / accumulation risk",
        f"A {GRID_CELL_SIZE_DEGREES:.0f}° grid over South Africa's bounding box scores each "
        "cell's historical hazard density (share of all footprint-bearing events that have ever "
        "touched it) against the portfolio's TIV share sitting in it. diversification_adjusted_pml "
        f"loads gross PML up by a penalty, capped at {MAX_CONCENTRATION_PENALTY:.0%}, proportional "
        "to how much TIV sits concentrated in historically hazard-dense cells — a documented "
        "placeholder loading, not a calibrated catastrophe-model accumulation charge.",
    ),
    (
        "Hazard footprints",
        "Footprints are from GDACS. Cyclone footprints use the first forecast cone segment, "
        "not a unioned track corridor.",
    ),
    (
        "Scope",
        "Single-country (ISO3) scope. Hazard source is GDACS only; no national "
        "meteorological-service feed is integrated.",
    ),
]


def render_html(report: DisclosureReport) -> str:
    ev_rows = "\n".join(
        f"""<tr>
          <td>{esc(e.event_name or f"{e.event_type} {e.event_id}")}
              <span class="muted">#{e.hazard_event_id}</span></td>
          <td>{esc(e.event_type)}</td>
          <td>{esc(e.from_date.date() if e.from_date else "—")}</td>
          <td><span class="badge" style="background:{_ALERT_BADGE.get(e.alert_level, "#64748b")}">{esc(e.alert_level or "—")}</span></td>
          <td class="num">{e.asset_count}</td>
          <td class="num">{_zar(e.tiv_at_risk)}</td>
          <td class="num">{_pct(e.damage_ratio)}</td>
          <td class="num">{_zar(e.probable_maximum_loss)}</td>
          <td class="num">{_zar(e.protection_gap)}</td>
        </tr>"""
        for e in report.events
    ) or '<tr><td colspan="9" class="muted">No hazard events in this period.</td></tr>'

    type_rows = "\n".join(
        f"""<tr><td>{esc(b.asset_type)}</td><td class="num">{b.count}</td>
            <td class="num">{_zar(b.total_insured_value)}</td></tr>"""
        for b in report.assets_by_type
    )

    method_rows = "\n".join(
        f"<tr><td><strong>{esc(t)}</strong></td><td>{esc(body)}</td></tr>"
        for t, body in _METHODOLOGY
    )

    p = report.parametric
    peak = report.peak_event_pml

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Climate risk disclosure — {esc(report.org_name)}</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ font: 13px/1.5 -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         color: #0f172a; max-width: 900px; margin: 0 auto; padding: 32px; background: #fff; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  h2 {{ font-size: 15px; margin: 28px 0 8px; border-bottom: 2px solid #0f172a; padding-bottom: 4px; }}
  .sub {{ color: #475569; margin: 0 0 2px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 8px 0 4px; }}
  th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }}
  th {{ font-size: 10px; text-transform: uppercase; letter-spacing: .04em; color: #64748b; }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 10px 0; }}
  .card {{ border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; }}
  .card .k {{ font-size: 10px; text-transform: uppercase; letter-spacing: .04em; color: #64748b; }}
  .card .v {{ font-size: 17px; font-weight: 600; margin-top: 3px; font-variant-numeric: tabular-nums; }}
  .muted {{ color: #94a3b8; }}
  .badge {{ color: #fff; padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; }}
  .note {{ font-size: 11px; color: #64748b; margin-top: 4px; }}
  @media print {{ body {{ padding: 0; }} h2 {{ page-break-after: avoid; }} tr {{ page-break-inside: avoid; }} }}
</style></head><body>

<h1>Climate-related risk disclosure</h1>
<p class="sub">{esc(report.org_name)} — hazard scope {esc(report.iso3)}</p>
<p class="sub">Reporting period {esc(report.period_start)} to {esc(report.period_end)} ·
   generated {esc(report.generated_at.strftime("%Y-%m-%d %H:%M UTC"))}</p>

<h2>1 · Portfolio</h2>
<div class="cards">
  <div class="card"><div class="k">Insured assets</div><div class="v">{report.asset_count}</div></div>
  <div class="card"><div class="k">Total insured value</div><div class="v">{_zar(report.portfolio_tiv)}</div></div>
  <div class="card"><div class="k">Declared insured value</div><div class="v">{_zar(report.portfolio_declared_insured_value)}</div></div>
  <div class="card"><div class="k">Declared cover ratio</div><div class="v">{_pct((report.portfolio_declared_insured_value / report.portfolio_tiv) if report.portfolio_tiv else None)}</div></div>
</div>
<table><thead><tr><th>Asset type</th><th class="num">Count</th><th class="num">TIV</th></tr></thead>
<tbody>{type_rows}</tbody></table>

<h2>2 · Hazard exposure in the period</h2>
<div class="cards">
  <div class="card"><div class="k">Hazard events</div><div class="v">{report.event_count}</div></div>
  <div class="card"><div class="k">Distinct assets exposed</div><div class="v">{report.distinct_assets_exposed}</div></div>
  <div class="card"><div class="k">Distinct TIV exposed</div><div class="v">{_zar(report.distinct_tiv_exposed)}</div></div>
  <div class="card"><div class="k">Est. protection gap (exposed)</div><div class="v">{_zar(report.protection_gap_on_distinct)}</div></div>
  <div class="card"><div class="k">Compound-exposure share of PML</div><div class="v">{_pct(report.compound_pml_pct)}</div></div>
  <div class="card"><div class="k">Diversification-adjusted PML</div><div class="v">{_zar(report.diversification_adjusted_pml)}</div></div>
</div>
<p class="note">"Distinct" figures de-duplicate assets hit by more than one event.
   Peak single-event PML:
   {esc(peak.event_name or (f"{peak.event_type} {peak.event_id}" if peak else "none"))}
   — {_zar(peak.probable_maximum_loss if peak else 0)}.
   Gross (non-deduplicated) Σ TIV-at-risk {_zar(report.gross_tiv_at_risk)},
   gross Σ PML {_zar(report.gross_pml)}.</p>
<table><thead><tr>
  <th>Event</th><th>Type</th><th>Date</th><th>Alert</th>
  <th class="num">Assets</th><th class="num">TIV at risk</th><th class="num">Damage ratio</th>
  <th class="num">PML</th><th class="num">Protection gap</th>
</tr></thead><tbody>{ev_rows}</tbody></table>

<h2>3 · Parametric coverage position</h2>
<div class="cards">
  <div class="card"><div class="k">Active rules</div><div class="v">{p.get("active_rule_count", 0)} / {p.get("rule_count", 0)}</div></div>
  <div class="card"><div class="k">Firings</div><div class="v">{p.get("firing_count", 0)}</div></div>
  <div class="card"><div class="k">Outstanding payout</div><div class="v">{_zar(p.get("total_outstanding_payout", 0))}</div></div>
  <div class="card"><div class="k">Net basis risk</div><div class="v">{_zar(p.get("total_basis_risk", 0))}</div></div>
</div>
<p class="note">Basis risk = modelled parametric payout − modelled PML. Positive ⇒ cover pays more
   than the modelled loss for the events on the ledger.</p>

<h2>4 · Methodology &amp; limitations</h2>
<table><tbody>{method_rows}</tbody></table>

<p class="note">Generated by ClimRisk. Figures are model estimates for internal risk screening,
   not audited financial statements.</p>
</body></html>"""
