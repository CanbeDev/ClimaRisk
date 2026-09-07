"""Damage ratio bands for PML (Probable Maximum Loss) estimation.

PML = Exposure at Risk x Damage Ratio (ClimRisk Master Document, Section 4.3).
The bands below are HAZUS-MH / FEMA depth-damage-curve convention, cited from
the master document rather than invented here.

The master document calibrates ratio bands against hazard-specific severity
(flood depth in metres, cyclone category, "direct contact" for wildfire) —
none of which GDACS exposes to this pipeline today. As a documented
simplification, GDACS's own `alert_level` (Green/Orange/Red, its own
event-severity classification) stands in as a minor/major proxy within each
hazard type, and the band *midpoint* is used rather than calibrating further
within the band — the same approach the master document names explicitly
("GDACS's per-event severity/vulnerability fields ... can calibrate within a
band rather than always using the midpoint" — not yet implemented here).

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


def get_damage_ratio(event_type: str, alert_level: str | None) -> float:
    """Return the band-midpoint damage ratio for a hazard type + alert level.

    Always returns a usable float — falls back to `_DEFAULT_BAND`'s midpoint
    for hazard types or alert levels not covered above, logging that the
    fallback was used so it's traceable rather than silently approximate.
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

    return round((low + high) / 2, 4)
