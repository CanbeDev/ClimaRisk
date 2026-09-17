"""Damage ratio bands for PML (Probable Maximum Loss) estimation.

PML = Exposure at Risk x Damage Ratio (ClimRisk Master Document, Section 4.3).
The bands below are HAZUS-MH / FEMA depth-damage-curve convention, cited from
the master document rather than invented here.

The master document calibrates ratio bands against hazard-specific severity
(flood depth in metres, cyclone category, "direct contact" for wildfire) —
none of which GDACS exposes to this pipeline today. GDACS's own `alert_level`
(Green/Orange/Red, its own event-severity classification) stands in as a
minor/major proxy within each hazard type, selecting which band applies.

Within a band, the ratio no longer collapses to the midpoint (the pre-Step-1
behaviour): it interpolates linearly on `proximity_score` — how close the
asset sits to the hazard footprint's centroid (1.0) versus its edge (0.0),
computed in `app/services/intersection.py`. An asset dead-center in a Red
flood gets the band's major end; one just inside the edge of the same event
gets close to the minor end. This replaces one documented simplification
(always the midpoint) with a different, still-documented one (linear decay
by distance, not by physical severity such as flood depth) — closer to the
master document's own "calibrate within a band" intent than the midpoint was,
without requiring hazard-specific severity data GDACS doesn't provide.

Event types with no band in the master document (EQ, VO, DR) fall back to a
single conservative default band, logged so it's visible this is a stand-in,
not a researched figure.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# event_type -> alert_level -> (low, high) damage ratio band.
# Green/Orange are both treated as the "minor" end of each hazard's range;
# Red as the "major" end — GDACS's three alert levels don't map 1:1 onto the
# master document's flood-depth / cyclone-category bands, so this collapses
# them to the two ends of the documented range.
_DAMAGE_RATIO_BANDS: dict[str, dict[str, tuple[float, float]]] = {
    "FL": {  # Flood: minor vs. major (>1m depth)
        "Green": (0.05, 0.15),
        "Orange": (0.05, 0.15),
        "Red": (0.30, 0.60),
    },
    "TC": {  # Cyclone: Cat 1-2 vs. Cat 4-5
        "Green": (0.05, 0.20),
        "Orange": (0.05, 0.20),
        "Red": (0.40, 0.80),
    },
    "WF": {  # Wildfire: the master document gives one band ("direct contact")
        "Green": (0.70, 1.00),  # regardless of alert level — if a wildfire
        "Orange": (0.70, 1.00),  # footprint intersects an asset at all, that
        "Red": (0.70, 1.00),  # already implies direct contact.
    },
}

# EQ, VO, DR aren't in the master document's damage-ratio table. This is a
# deliberately conservative placeholder, not a researched band — callers get
# a value so PML always computes, but it should be replaced with real
# HAZUS-MH/FEMA-equivalent bands for these hazard types before the figure is
# used for anything beyond a rough demo.
_DEFAULT_BAND: tuple[float, float] = (0.10, 0.30)


def get_damage_ratio(event_type: str, alert_level: str | None, proximity_score: float) -> float:
    """Return the distance-decay damage ratio for a hazard type + alert level,
    interpolated within the band by `proximity_score`.

    `proximity_score` is 1.0 at the hazard footprint's centroid (the band's
    major/high end applies) and 0.0 at its edge (the band's minor/low end
    applies) — see `app/services/intersection.py` for how it's computed per
    asset. Values outside [0, 1] are clamped rather than trusted, since a
    caller could in principle pass a raw, unclamped ratio (e.g. an
    event-level average that rounds slightly outside the range).

        ratio = low + (high - low) * proximity_score

    Always returns a usable float — falls back to `_DEFAULT_BAND` for hazard
    types or alert levels not covered above, logging that the fallback was
    used so it's traceable rather than silently approximate.
    """
    bands = _DAMAGE_RATIO_BANDS.get(event_type)
    if bands is None:
        log.info(
            "No damage-ratio band for event_type=%s; using default band %s",
            event_type,
            _DEFAULT_BAND,
        )
        low, high = _DEFAULT_BAND
    else:
        band = bands.get(alert_level or "")
        if band is None:
            log.info(
                "No damage-ratio band for event_type=%s alert_level=%s; using Orange band",
                event_type,
                alert_level,
            )
            band = bands.get("Orange", _DEFAULT_BAND)
        low, high = band

    proximity_score = max(0.0, min(1.0, proximity_score))
    return round(low + (high - low) * proximity_score, 4)


def compute_pml(
    tiv: float,
    event_type: str,
    alert_level: str | None,
    proximity_score: float,
) -> float:
    """PML = Exposure at Risk x distance-decay Damage Ratio (Section 4.3).

    The single shared PML formula for every caller — `intersection.py` calls
    it once per exposed asset (each with its own `proximity_score`) and sums
    the results; `trends.py` calls it once per event using that event's
    TIV-weighted average `proximity_score` across its exposed assets. Because
    `get_damage_ratio` is linear in `proximity_score` and every asset behind
    one event shares the same `event_type`/`alert_level` band, those two are
    mathematically identical, not merely close — see trends.py's docstring
    for the derivation. Extracted so the two services can no longer drift
    apart the way their separately hand-written PML formulas could before.
    """
    return tiv * get_damage_ratio(event_type, alert_level, proximity_score)
