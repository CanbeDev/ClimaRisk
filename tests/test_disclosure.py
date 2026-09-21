"""Tests for the climate disclosure report (Step 8 / Phase 3).

Integration tests against the real database via DATABASE_URL, same style as the
other suites.
"""

from __future__ import annotations

from datetime import date, timedelta

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

# A clean square: its four corners are all exactly equidistant from its
# centroid, giving a hand-verifiable proximity_score (1.0 at the centroid)
# without depending on any real footprint's actual shape.
_SQUARE_WKT = "POLYGON((10 -30, 10.2 -30, 10.2 -29.8, 10 -29.8, 10 -30))"
_SQUARE_CENTROID_WKT = "POINT(10.1 -29.9)"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def portfolio_totals():
    conn = psycopg2.connect(get_settings().database_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), COALESCE(SUM(total_insured_value), 0) FROM assets")
            count, tiv = cur.fetchone()
        return {"count": count, "tiv": float(tiv)}
    finally:
        conn.close()


def test_disclosure_json_shape_and_portfolio(client, portfolio_totals):
    body = client.get("/reports/disclosure").json()

    assert set(body) >= {"org_name", "iso3", "period_start", "period_end", "portfolio", "hazard_exposure", "parametric_position"}
    assert body["portfolio"]["asset_count"] == portfolio_totals["count"]
    assert body["portfolio"]["total_insured_value"] == pytest.approx(portfolio_totals["tiv"])
    # by_type counts sum back to the whole book
    assert sum(b["count"] for b in body["portfolio"]["by_type"]) == portfolio_totals["count"]


def test_disclosure_period_filters_events(client):
    all_events = client.get("/reports/disclosure").json()["hazard_exposure"]["events"]
    assert len(all_events) >= 1

    future = client.get("/reports/disclosure", params={"from": "2099-01-01"}).json()
    assert future["hazard_exposure"]["event_count"] == 0
    assert future["hazard_exposure"]["distinct_assets_exposed"] == 0

    # A window around a known ZAF flood (FL 1101354, 2022-04-09) keeps at least that one.
    windowed = client.get(
        "/reports/disclosure", params={"from": "2022-01-01", "to": "2022-12-31"}
    ).json()
    assert 1 <= windowed["hazard_exposure"]["event_count"] <= len(all_events)
    assert all(e["from_date"][:4] == "2022" for e in windowed["hazard_exposure"]["events"])


def test_disclosure_rejects_backwards_period(client):
    resp = client.get("/reports/disclosure", params={"from": "2025-01-01", "to": "2024-01-01"})
    assert resp.status_code == 422


def test_disclosure_pml_matches_intersection_service(client):
    """The report reuses the trend service, which shares damage_ratio with the
    intersection service — so a firing event's PML must line up with
    /exposure/intersect for the same event, up to Step 3's one deliberate
    exception: run_hazard_trends()'s grouped join has no per-asset history to
    detect multi-hazard compounding, so /exposure/intersect's PML can be
    strictly higher for an event where a contributing asset was already hit
    by another event in the compounding window (see
    app/services/compounding.py) — never lower, and equal whenever no
    contributing asset compounds. TIV is unaffected by compounding either
    way, so that equality still holds exactly."""
    report = client.get("/reports/disclosure").json()
    firing = [e for e in report["hazard_exposure"]["events"] if e["asset_count"] > 0]
    if not firing:
        pytest.skip("no firing events in the demo dataset")

    e = firing[0]
    direct = client.get(f"/exposure/intersect/{e['hazard_event_id']}").json()
    assert direct["probable_maximum_loss"] >= e["probable_maximum_loss"] - 1e-6
    if not any(a["is_compound_loss"] for a in direct["assets"]):
        assert e["probable_maximum_loss"] == pytest.approx(direct["probable_maximum_loss"])
    assert e["tiv_at_risk"] == pytest.approx(direct["total_insured_value"])


def test_compound_exposure_flag_and_aggregate(client):
    """Two events sharing the same footprint, 10 days apart (inside the
    30-day compounding window), both hitting one shared asset at the exact
    centroid: the later event should see the earlier as a prior hit on that
    asset (is_compound_loss True, compound_multiplier 1.15x), the earlier
    should not (it's the first hit), and the disclosure aggregate's
    compound_pml_contribution should reflect exactly that.

    Asserts on *deltas* around a narrow period window (like the rest of this
    suite does around baselines) rather than the window's absolute totals,
    so this can't be broken by whatever real seed/backfilled data happens to
    also fall in that window on a given database.
    """
    window_from = (date.today() - timedelta(days=25)).isoformat()
    window_to = (date.today() + timedelta(days=1)).isoformat()

    baseline = client.get(
        "/reports/disclosure", params={"from": window_from, "to": window_to}
    ).json()["hazard_exposure"]

    conn = psycopg2.connect(get_settings().database_url)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO hazard_events (
            event_type, event_id, episode_id, event_name,
            alert_level, iso3, affected_countries, from_date, centroid, footprint
        ) VALUES
          ('FL', 999900004, 1, 'Compound test event 1 (earlier)',
           'Red', 'ZAF', ARRAY['ZAF'], now() - INTERVAL '20 days',
           ST_GeomFromText(%(centroid)s, 4326), ST_GeomFromText(%(footprint)s, 4326)),
          ('FL', 999900005, 1, 'Compound test event 2 (later)',
           'Red', 'ZAF', ARRAY['ZAF'], now() - INTERVAL '10 days',
           ST_GeomFromText(%(centroid)s, 4326), ST_GeomFromText(%(footprint)s, 4326))
        ON CONFLICT (event_type, event_id, episode_id) DO UPDATE SET from_date = EXCLUDED.from_date
        RETURNING id
        """,
        {"centroid": _SQUARE_CENTROID_WKT, "footprint": _SQUARE_WKT},
    )
    event1_id, event2_id = [row[0] for row in cur.fetchall()]

    cur.execute(
        """
        INSERT INTO assets (asset_name, asset_type, location, building_value, contents_value)
        VALUES ('Compound test asset', 'commercial', ST_GeomFromText(%s, 4326), 1000000, 0)
        RETURNING id
        """,
        (_SQUARE_CENTROID_WKT,),
    )
    asset_id = cur.fetchone()[0]
    conn.commit()

    try:
        direct1 = client.get(f"/exposure/intersect/{event1_id}").json()
        direct2 = client.get(f"/exposure/intersect/{event2_id}").json()
        a1 = next(a for a in direct1["assets"] if a["id"] == asset_id)
        a2 = next(a for a in direct2["assets"] if a["id"] == asset_id)

        # event1 is the first hit on this asset -- nothing prior to compound against.
        assert a1["is_compound_loss"] is False
        assert a1["compound_multiplier"] == pytest.approx(1.0)

        # event2 sees event1 (10 days earlier, inside the 30-day window) as a
        # prior hit on this same asset.
        assert a2["is_compound_loss"] is True
        assert a2["compound_multiplier"] == pytest.approx(1.15)
        assert a2["damage_ratio"] == pytest.approx(min(1.0, a1["damage_ratio"] * 1.15))

        after = client.get(
            "/reports/disclosure", params={"from": window_from, "to": window_to}
        ).json()["hazard_exposure"]

        delta_gross_pml = after["gross_probable_maximum_loss"] - baseline["gross_probable_maximum_loss"]
        delta_compound = after["compound_pml_contribution"] - baseline["compound_pml_contribution"]

        # Only event2's asset entry is a compound loss -> its contribution is
        # the whole delta.
        assert delta_compound == pytest.approx(a2["total_insured_value"] * a2["damage_ratio"], rel=1e-6)

        # Both events share the same footprint and the same asset at each
        # one's exact centroid, so the (non-compounded) trend-service PML is
        # identical for both -> delta_gross_pml = 2 * base_pml, while
        # delta_compound = base_pml * 1.15 (the cap never binds: FL's highest
        # band is 0.60, and 0.60 * 1.15 < 1.0). The ratio of deltas is then
        # exactly 1.15 / 2, independent of whatever this window's absolute
        # totals happen to include from real data.
        assert delta_gross_pml > 0
        assert delta_compound / delta_gross_pml == pytest.approx(0.575, rel=1e-3)
    finally:
        cur.execute("DELETE FROM assets WHERE id = %s", (asset_id,))
        cur.execute("DELETE FROM hazard_events WHERE id = ANY(%s)", ([event1_id, event2_id],))
        conn.commit()
        cur.close()
        conn.close()


_CONCENTRATION_CELL_HAZARD_FOOTPRINT_WKT = (
    "POLYGON((20.01 -29.99, 20.05 -29.99, 20.05 -29.95, 20.01 -29.95, 20.01 -29.99))"
)
# Same 1-degree grid cell [20,21) x [-30,-29) as the footprint above, but far
# enough from it that ST_Intersects is false -- the clustered asset shares a
# *grid cell* with the calibration hazard events (what concentration scores)
# without geometrically touching them (so it contributes no PML to them,
# keeping gross_pml unaffected by which scenario -- clustered or diversified
# -- is currently inserted).
_CONCENTRATION_CLUSTERED_POINT_WKT = "POINT(20.8 -29.2)"

# Ten points, each in a distinct 1-degree cell, all clear of [20,21)x[-30,-29).
_CONCENTRATION_DIVERSIFIED_POINTS_WKT = [
    "POINT(16.5 -34.5)",
    "POINT(18.5 -32.5)",
    "POINT(21.5 -27.5)",
    "POINT(23.5 -25.5)",
    "POINT(25.5 -23.5)",
    "POINT(27.5 -33.5)",
    "POINT(29.5 -30.5)",
    "POINT(31.5 -24.5)",
    "POINT(17.5 -28.5)",
    "POINT(19.5 -31.5)",
]


def test_diversification_adjusted_pml_higher_when_clustered(client):
    """A large TIV concentrated in one grid cell with a manufactured history
    of hazard activity should score a higher concentration_index (and
    therefore a higher diversification_adjusted_pml) than the exact same
    total TIV spread across ten separate, otherwise-unremarkable cells.

    Ten synthetic calibration hazard events are inserted in one specific
    cell so that cell's hazard density is robustly the highest in the grid
    regardless of whatever real historical events already exist elsewhere --
    without this, the test would be at the mercy of wherever this database's
    real (and unknown to this test) historical events happen to be densest.
    Their footprint is placed in a corner of that cell the clustered asset
    never touches, so they never contribute PML to gross_pml themselves;
    only concentration_index (and, through it, diversification_adjusted_pml)
    is expected to differ between the two scenarios.
    """
    conn = psycopg2.connect(get_settings().database_url)
    cur = conn.cursor()

    hazard_ids = []
    for i in range(10):
        cur.execute(
            """
            INSERT INTO hazard_events (
                event_type, event_id, episode_id, event_name,
                alert_level, iso3, affected_countries, from_date, centroid, footprint
            ) VALUES (
                'FL', %s, 1, 'Concentration test calibration hazard',
                'Orange', 'ZAF', ARRAY['ZAF'], now() - make_interval(days => %s),
                ST_Centroid(ST_GeomFromText(%s, 4326)), ST_GeomFromText(%s, 4326)
            )
            ON CONFLICT (event_type, event_id, episode_id) DO UPDATE SET iso3 = EXCLUDED.iso3
            RETURNING id
            """,
            (
                999901000 + i,
                200 + i,
                _CONCENTRATION_CELL_HAZARD_FOOTPRINT_WKT,
                _CONCENTRATION_CELL_HAZARD_FOOTPRINT_WKT,
            ),
        )
        hazard_ids.append(cur.fetchone()[0])
    conn.commit()

    total_tiv = 50_000_000_000  # overwhelms any realistic demo-scale background TIV

    def _insert_assets(points_wkt: list[str]) -> list[int]:
        per_asset = total_tiv / len(points_wkt)
        values_sql = ", ".join(["(%s, 'commercial', ST_GeomFromText(%s, 4326), %s, 0)"] * len(points_wkt))
        params = [v for wkt in points_wkt for v in ("Concentration test asset", wkt, per_asset)]
        cur.execute(
            f"INSERT INTO assets (asset_name, asset_type, location, building_value, contents_value) "
            f"VALUES {values_sql} RETURNING id",
            params,
        )
        ids = [row[0] for row in cur.fetchall()]
        conn.commit()
        return ids

    def _delete_assets(ids: list[int]) -> None:
        if ids:
            cur.execute("DELETE FROM assets WHERE id = ANY(%s)", (ids,))
            conn.commit()

    try:
        clustered_ids = _insert_assets([_CONCENTRATION_CLUSTERED_POINT_WKT])
        try:
            clustered = client.get("/reports/disclosure").json()["hazard_exposure"]
        finally:
            _delete_assets(clustered_ids)

        diversified_ids = _insert_assets(_CONCENTRATION_DIVERSIFIED_POINTS_WKT)
        try:
            diversified = client.get("/reports/disclosure").json()["hazard_exposure"]
        finally:
            _delete_assets(diversified_ids)

        assert clustered["concentration_index"] > diversified["concentration_index"]
        assert clustered["diversification_adjusted_pml"] >= diversified["diversification_adjusted_pml"]
        # gross_pml is untouched by either scenario (neither the clustered nor
        # the diversified asset set geometrically intersects the calibration
        # footprint or any real event this test doesn't control), so the
        # diversification_adjusted_pml gap above is attributable to the
        # concentration penalty alone, not a shifting multiplicand.
        assert clustered["gross_probable_maximum_loss"] == pytest.approx(
            diversified["gross_probable_maximum_loss"]
        )
    finally:
        cur.execute("DELETE FROM hazard_events WHERE id = ANY(%s)", (hazard_ids,))
        conn.commit()
        cur.close()
        conn.close()


def test_disclosure_html_renders(client):
    resp = client.get("/reports/disclosure.html")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    html = resp.text
    assert get_settings().report_org_name in html
    assert "Methodology" in html
    assert "<h2>" in html
