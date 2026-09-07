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

    # PML: damage_ratio is alert_level-dependent (real DB data), but must
    # always be a valid FL band midpoint, and PML must equal TIV x ratio.
    assert body["damage_ratio"] in (pytest.approx(0.10), pytest.approx(0.45))
    assert body["probable_maximum_loss"] == pytest.approx(
        body["total_insured_value"] * body["damage_ratio"]
    )


def test_nonexistent_hazard_event_returns_404(client):
    response = client.get("/exposure/intersect/999999999")
    assert response.status_code == 404
