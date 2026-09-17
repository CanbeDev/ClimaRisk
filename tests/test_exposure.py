"""Tests for GET /exposure/intersect/{hazard_event_id} (Step 3 API layer).

These are integration tests against the real database configured via
DATABASE_URL — same as the rest of this project, there is no DB mocking.
Run with:

    pytest tests/test_exposure.py
"""

from __future__ import annotations

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

# Mirrors app/services/damage_ratio.py's FL band (Green/Orange share the minor
# band; Red is the major band) — kept local rather than importing the
# module's private `_DAMAGE_RATIO_BANDS` so this test pins the same public
# contract a caller would rely on, not an implementation detail.
_FL_BANDS = {"Green": (0.05, 0.15), "Orange": (0.05, 0.15), "Red": (0.30, 0.60)}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def zaf_flood_hazard_id() -> int:
    """hazard_events.id of a real, footprint-bearing ZAF event (Step 1 data)."""
    settings = get_settings()
    conn = psycopg2.connect(settings.database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM hazard_events
                WHERE event_type = 'FL' AND event_id = 1101354 AND footprint IS NOT NULL
                """
            )
            row = cur.fetchone()
        if row is None:
            pytest.skip("Reference hazard event (FL 1101354) not present in this database")
        return row[0]
    finally:
        conn.close()


@pytest.fixture()
def bracketing_assets(client, zaf_flood_hazard_id: int):
    """Insert one asset inside the event footprint and one clearly outside it.

    Mirrors the manual verification done for app/services/intersection.py:
    a controlled inside/outside pair proves ST_Intersects is discriminating
    real geometry, not just returning everything. Cleaned up afterward.

    The DB may already hold unrelated (seed/demo) assets that intersect this
    footprint, so a `baseline` snapshot is taken *before* the inserts — the
    test asserts on the delta this pair causes, not on absolute totals.
    """
    baseline = client.get(f"/exposure/intersect/{zaf_flood_hazard_id}")
    assert baseline.status_code == 200

    settings = get_settings()
    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()

    cur.execute(
        "SELECT ST_AsText(ST_PointOnSurface(footprint)) FROM hazard_events WHERE id = %s",
        (zaf_flood_hazard_id,),
    )
    interior_point_wkt = cur.fetchone()[0]

    cur.execute(
        """
        INSERT INTO assets (
            asset_name, asset_type, location,
            building_value, contents_value, daily_net_revenue, insured_value
        ) VALUES
          ('Test Inside Asset', 'commercial', ST_GeomFromText(%s, 4326),
           1000000, 250000, 5000, 500000),
          ('Test Outside Asset', 'commercial',
           ST_SetSRID(ST_MakePoint(18.42, -33.92), 4326),
           2000000, 500000, 8000, 2500000)
        RETURNING id;
        """,
        (interior_point_wkt,),
    )
    asset_ids = [row[0] for row in cur.fetchall()]
    conn.commit()

    yield {
        "baseline": baseline.json(),
        "inside_id": asset_ids[0],
        "outside_id": asset_ids[1],
        "ids": asset_ids,
    }

    cur.execute("DELETE FROM assets WHERE id = ANY(%s)", (asset_ids,))
    conn.commit()
    cur.close()
    conn.close()


def test_intersection_returns_expected_financials(client, zaf_flood_hazard_id, bracketing_assets):
    baseline = bracketing_assets["baseline"]
    response = client.get(f"/exposure/intersect/{zaf_flood_hazard_id}")
    assert response.status_code == 200

    body = response.json()
    assert body["hazard_event_id"] == zaf_flood_hazard_id
    assert body["has_footprint"] is True

    returned_ids = {a["id"] for a in body["assets"]}
    # The inside asset must intersect; the Cape Town one must not — and its
    # insured_value (2,500,000) must not leak into the totals either.
    assert bracketing_assets["inside_id"] in returned_ids
    assert bracketing_assets["outside_id"] not in returned_ids

    # Assert on the delta this pair causes, so unrelated seed assets that also
    # intersect this footprint don't break the exact-value checks.
    assert body["asset_count"] - baseline["asset_count"] == 1
    assert body["total_insured_value"] - baseline["total_insured_value"] == pytest.approx(1_250_000.0)
    assert body["total_daily_net_revenue"] - baseline["total_daily_net_revenue"] == pytest.approx(5_000.0)
    assert body["total_declared_insured_value"] - baseline["total_declared_insured_value"] == pytest.approx(
        500_000.0
    )
    # Inside asset: TIV 1,250,000 declared 500,000 -> gap grows by 750,000.
    assert body["protection_gap"] - baseline["protection_gap"] == pytest.approx(750_000.0)

    # damage_ratio is now (Step 1) a TIV-weighted *effective* ratio across
    # whatever assets intersect — it can land anywhere inside the applicable
    # FL band rather than pinning to one exact value, since it depends on
    # where each intersecting asset sits relative to the footprint (real seed
    # assets included, whose positions this test doesn't control). It must
    # still fall inside the band real alert_level implies, and PML must
    # always equal TIV x that effective ratio (an identity by construction).
    low, high = _FL_BANDS.get(body["alert_level"], (0.05, 0.60))
    assert low - 1e-6 <= body["damage_ratio"] <= high + 1e-6
    assert body["probable_maximum_loss"] == pytest.approx(
        body["total_insured_value"] * body["damage_ratio"]
    )


def test_damage_ratio_interpolates_by_proximity(client, zaf_flood_hazard_id):
    """Step 1: within one event's band, damage_ratio decays with distance
    from the footprint's centroid rather than always landing on the midpoint.

    Two constructed points, robust to whatever shape the real footprint has:
      * `ST_PointOnSurface(footprint)` — guaranteed strictly inside, for any
        polygon/multipolygon subtype.
      * `ST_EndPoint(ST_LongestLine(ST_Centroid(footprint), ST_Boundary(footprint)))`
        — the single boundary vertex farthest from the centroid. Under
        intersection.py's own proximity_score formula that point's distance
        from the centroid *is* the normalising radius, so its
        proximity_score is 0.0 exactly, not just "close to the edge" —
        letting this test assert an exact value, not just a direction.
    """
    settings = get_settings()
    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT ST_AsText(ST_PointOnSurface(footprint)),
               ST_AsText(ST_EndPoint(ST_LongestLine(ST_Centroid(footprint), ST_Boundary(footprint))))
        FROM hazard_events WHERE id = %s
        """,
        (zaf_flood_hazard_id,),
    )
    interior_wkt, edge_wkt = cur.fetchone()

    cur.execute(
        """
        INSERT INTO assets (asset_name, asset_type, location, building_value, contents_value)
        VALUES
          ('Test Centroid Asset', 'commercial', ST_GeomFromText(%s, 4326), 1000000, 0),
          ('Test Edge Asset', 'commercial', ST_GeomFromText(%s, 4326), 1000000, 0)
        RETURNING id;
        """,
        (interior_wkt, edge_wkt),
    )
    asset_ids = [row[0] for row in cur.fetchall()]
    conn.commit()

    try:
        response = client.get(f"/exposure/intersect/{zaf_flood_hazard_id}")
        assert response.status_code == 200
        body = response.json()
        by_id = {a["id"]: a for a in body["assets"]}

        assert asset_ids[0] in by_id
        # ST_Intersects includes the boundary itself, so a point exactly on
        # it must still show up as exposed, not silently dropped.
        assert asset_ids[1] in by_id

        centroid_asset = by_id[asset_ids[0]]
        edge_asset = by_id[asset_ids[1]]
        low, high = _FL_BANDS.get(body["alert_level"], (0.05, 0.60))

        assert edge_asset["proximity_score"] == pytest.approx(0.0, abs=1e-6)
        assert edge_asset["damage_ratio"] == pytest.approx(low, abs=1e-3)

        assert low - 1e-6 <= centroid_asset["damage_ratio"] <= high + 1e-6
        assert centroid_asset["proximity_score"] > edge_asset["proximity_score"]
        assert centroid_asset["damage_ratio"] > edge_asset["damage_ratio"]

        # Per-asset PML must equal that asset's own TIV x its own ratio, even
        # though the two assets sit on the same event with different ratios.
        assert centroid_asset["probable_maximum_loss"] == pytest.approx(
            centroid_asset["total_insured_value"] * centroid_asset["damage_ratio"]
        )
        assert edge_asset["probable_maximum_loss"] == pytest.approx(
            edge_asset["total_insured_value"] * edge_asset["damage_ratio"]
        )
    finally:
        cur.execute("DELETE FROM assets WHERE id = ANY(%s)", (asset_ids,))
        conn.commit()
        cur.close()
        conn.close()


def test_nonexistent_hazard_event_returns_404(client):
    response = client.get("/exposure/intersect/999999999")
    assert response.status_code == 404
