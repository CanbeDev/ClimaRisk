"""Multi-hazard compounding (Step 3): an asset hit by more than one hazard
within a short window is worse off on the second hit than the isolated,
single-event damage ratio bands assume — a roof already breached, drainage
already saturated, a business already interrupted. This module holds the
pure multiplier math and its constants; the *count* of prior in-window hits
on a specific asset is fetched by the same single-round-trip query
`app/services/intersection.py` already runs per asset (see
`_fetch_intersecting_assets`), not a second spatial pass here — this stays a
small, dependency-free module so that query has something to import without
either service owning the other's concern.

This is deliberately per-asset, not per-event: an event that compounds one
asset's third hit this month can, in the same footprint, be a first-ever hit
for the asset next door. Compounding is a property of *that specific asset's
history*, not of the event as a whole.
"""

from __future__ import annotations

# How far back a prior hit on the *same* asset still counts as compounding
# rather than an unrelated, fully-recovered-from event. 30 days is a
# defensible round number in the same spirit as this codebase's other
# unmodelled physical detail (the HAZUS band table, the single-cone cyclone
# footprint) — not a calibrated recovery curve. A real figure would vary by
# asset type (a warehouse's drainage clears differently than a data centre's
# does) and by hazard (flood saturation clears faster than fire structural
# damage), neither of which this pipeline has data for yet.
COMPOUND_WINDOW_DAYS = 30

# Applied once per prior in-window hit on that specific asset, compounding
# multiplicatively (1.15, 1.15^2, 1.15^3, ...) rather than adding a flat
# 15% per hit — repeated damage to an already-weakened asset is the more
# defensible assumption than a fixed increment regardless of how many times
# it's already been hit, and it matches what "compounding" means elsewhere
# (interest, not a running total).
COMPOUND_MULTIPLIER_PER_HIT = 1.15

# A damage ratio is a fraction of TIV; "150% of the building" has no meaning
# however many prior hits compound into it.
MAX_DAMAGE_RATIO = 1.0


def compound_multiplier(prior_hit_count: int) -> float:
    """1.0 (no change) for an asset with no prior in-window hit;
    `COMPOUND_MULTIPLIER_PER_HIT` raised to the prior-hit count otherwise."""
    if prior_hit_count <= 0:
        return 1.0
    return COMPOUND_MULTIPLIER_PER_HIT**prior_hit_count


def apply_compound_multiplier(base_ratio: float, prior_hit_count: int) -> float:
    """Apply the compounding multiplier to a base (distance-decayed) damage
    ratio, capped at `MAX_DAMAGE_RATIO`."""
    return min(MAX_DAMAGE_RATIO, base_ratio * compound_multiplier(prior_hit_count))
