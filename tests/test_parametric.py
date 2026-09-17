"""Tests for the parametric trigger rules engine (Step 7 / Phase 2).

Integration tests against the real database via DATABASE_URL, same style as
test_exposure.py — no DB mocking. They reuse the real hazard event FL 1101354
(footprint-bearing, with intersecting seed assets) and assert on the delta the
test's own trigger causes, so unrelated rules in the table don't break them.
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


@pytest.fixture(scope="module")
def auth_headers() -> dict[str, str]:
    key = get_settings().ingest_api_key
    return {"X-API-Key": key} if key else {}


@pytest.fixture(scope="module")
def parametric_schema():
    """Skip the whole module if migration 008 hasn't been applied yet."""
    conn = psycopg2.connect(get_settings().database_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.parametric_triggers')")
            if cur.fetchone()[0] is None:
                pytest.skip("migration 008 (parametric_triggers) not applied to this database")
    finally:
        conn.close()


@pytest.fixture()
def zaf_flood_hazard_id() -> int:
    conn = psycopg2.connect(get_settings().database_url)
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
def zero_exposure_event():
    """A synthetic ZAF-tagged event whose footprint sits far from any real
    asset (open ocean) -- for horizontal_basis_risk_flag's "paid on the
    index, not on any real exposure" case, which needs an event guaranteed
    to expose nothing rather than relying on a real event's current (and
    possibly changing) seed-asset overlap."""
    conn = psycopg2.connect(get_settings().database_url)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO hazard_events (
            event_type, event_id, episode_id, event_name,
            alert_level, iso3, affected_countries, from_date,
            centroid, footprint
        ) VALUES (
            'FL', 999900002, 1, 'Open ocean flood (test, no exposure)',
            'Orange', 'ZAF', ARRAY['ZAF'], now(),
            ST_SetSRID(ST_MakePoint(0.0, -40.0), 4326),
            ST_GeomFromText('POLYGON((-0.1 -40.1, 0.1 -40.1, 0.1 -39.9, -0.1 -39.9, -0.1 -40.1))', 4326)
        )
        ON CONFLICT (event_type, event_id, episode_id) DO UPDATE SET iso3 = EXCLUDED.iso3
        RETURNING id
        """
    )
    event_id = cur.fetchone()[0]
    conn.commit()
    yield event_id
    cur.execute("DELETE FROM hazard_events WHERE id = %s", (event_id,))
    conn.commit()
    cur.close()
    conn.close()


@pytest.fixture()
def spatial_test_event():
    """A synthetic ZAF-tagged, perfectly square footprint far from any real
    asset. A square's corners are all exactly equidistant from its centroid,
    so placing assets at known corners/centroid gives hand-verifiable
    proximity_score values -- the real FL 1101354 footprint's exact shape
    isn't known/controllable from a test."""
    conn = psycopg2.connect(get_settings().database_url)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO hazard_events (
            event_type, event_id, episode_id, event_name,
            alert_level, iso3, affected_countries, from_date,
            centroid, footprint
        ) VALUES (
            'FL', 999900003, 1, 'Synthetic square flood (test)',
            'Orange', 'ZAF', ARRAY['ZAF'], now(),
            ST_GeomFromText('POINT(10.1 -29.9)', 4326),
            ST_GeomFromText('POLYGON((10 -30, 10.2 -30, 10.2 -29.8, 10 -29.8, 10 -30))', 4326)
        )
        ON CONFLICT (event_type, event_id, episode_id) DO UPDATE SET iso3 = EXCLUDED.iso3
        RETURNING id
        """
    )
    event_id = cur.fetchone()[0]
    conn.commit()
    yield event_id
    cur.execute("DELETE FROM hazard_events WHERE id = %s", (event_id,))
    conn.commit()
    cur.close()
    conn.close()


@pytest.fixture()
def make_trigger(client, auth_headers, parametric_schema):
    """Create triggers via the API and delete them (firings cascade) on teardown."""
    created: list[int] = []

    def _create(**overrides):
        body = {
            "name": overrides.pop("name", "pytest-trigger"),
            "event_type": "FL",
            "min_alert_level": "Orange",
            "requires_exposed_assets": True,
            "payout_kind": "fixed",
            "payout_value": 10_000_000,
            **overrides,
        }
        resp = client.post("/parametric/triggers", json=body, headers=auth_headers)
        assert resp.status_code == 201, resp.text
        tid = resp.json()["id"]
        created.append(tid)
        return tid

    yield _create

    for tid in created:
        client.delete(f"/parametric/triggers/{tid}", headers=auth_headers)


def _pick(evaluations, trigger_id):
    return next(e for e in evaluations if e["trigger_id"] == trigger_id)


def test_fixed_trigger_fires_with_basis_risk_vs_pml(client, auth_headers, make_trigger, zaf_flood_hazard_id):
    tid = make_trigger(name="pytest-fixed", payout_value=10_000_000)

    exposure = client.get(f"/exposure/intersect/{zaf_flood_hazard_id}").json()
    pml = exposure["probable_maximum_loss"]
    assert exposure["asset_count"] > 0  # precondition: event exposes assets

    resp = client.post(f"/parametric/evaluate/{zaf_flood_hazard_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    ev = _pick(resp.json()["evaluations"], tid)

    assert ev["fired"] is True
    assert ev["payout_amount"] == pytest.approx(10_000_000)
    assert ev["modelled_loss"] == pytest.approx(pml)
    assert ev["vertical_basis_risk"] == pytest.approx(10_000_000 - pml)
    # A fixed payout that did expose assets is neither the zero-exposure nor
    # the silent-rule case.
    assert ev["horizontal_basis_risk_flag"] is False
    # Nothing spatial to size for a fixed payout.
    assert ev["spatial_basis_risk_pct"] is None

    firings = client.get(f"/parametric/firings?hazard_event_id={zaf_flood_hazard_id}").json()["firings"]
    ours = _pick(firings, tid)
    assert ours["payout_amount"] == pytest.approx(10_000_000)
    assert ours["vertical_basis_risk"] == pytest.approx(10_000_000 - pml)


def test_alert_level_gate_blocks_firing(client, auth_headers, make_trigger, zaf_flood_hazard_id):
    # FL 1101354 is an Orange event; a Red floor must not fire.
    tid = make_trigger(name="pytest-red", min_alert_level="Red")

    resp = client.post(f"/parametric/evaluate/{zaf_flood_hazard_id}", headers=auth_headers)
    ev = _pick(resp.json()["evaluations"], tid)
    assert ev["fired"] is False
    assert "alert_level" in ev["reason"]

    firings = client.get(f"/parametric/firings?trigger_id={tid}").json()["firings"]
    assert firings == []


def test_reevaluation_removes_stale_firing(client, auth_headers, make_trigger, zaf_flood_hazard_id):
    tid = make_trigger(name="pytest-toggle", min_alert_level="Orange")

    client.post(f"/parametric/evaluate/{zaf_flood_hazard_id}", headers=auth_headers)
    assert client.get(f"/parametric/firings?trigger_id={tid}").json()["count"] == 1

    # Tighten so it no longer fires, re-evaluate: the stale payout row must go.
    patch = client.patch(
        f"/parametric/triggers/{tid}", json={"min_alert_level": "Red"}, headers=auth_headers
    )
    assert patch.status_code == 200, patch.text
    client.post(f"/parametric/evaluate/{zaf_flood_hazard_id}", headers=auth_headers)
    assert client.get(f"/parametric/firings?trigger_id={tid}").json()["count"] == 0


def test_deactivating_a_rule_clears_its_firings(client, auth_headers, make_trigger, zaf_flood_hazard_id):
    tid = make_trigger(name="pytest-deactivate", min_alert_level="Orange")

    client.post(f"/parametric/evaluate/{zaf_flood_hazard_id}", headers=auth_headers)
    assert client.get(f"/parametric/firings?trigger_id={tid}").json()["count"] == 1

    patch = client.patch(
        f"/parametric/triggers/{tid}", json={"is_active": False}, headers=auth_headers
    )
    assert patch.status_code == 200
    assert client.get(f"/parametric/firings?trigger_id={tid}").json()["count"] == 0


def test_tiv_share_payout_matches_exposure(client, auth_headers, make_trigger, zaf_flood_hazard_id):
    tid = make_trigger(name="pytest-tivshare", payout_kind="tiv_share", payout_value=0.25)

    tiv = client.get(f"/exposure/intersect/{zaf_flood_hazard_id}").json()["total_insured_value"]
    resp = client.post(f"/parametric/evaluate/{zaf_flood_hazard_id}", headers=auth_headers)
    ev = _pick(resp.json()["evaluations"], tid)

    assert ev["fired"] is True
    assert ev["payout_amount"] == pytest.approx(0.25 * tiv)


def test_summary_reflects_a_firing(client, auth_headers, make_trigger, zaf_flood_hazard_id):
    before = client.get("/parametric/summary").json()

    tid = make_trigger(name="pytest-summary", payout_value=7_000_000)
    client.post(f"/parametric/evaluate/{zaf_flood_hazard_id}", headers=auth_headers)

    after = client.get("/parametric/summary").json()
    assert after["rule_count"] == before["rule_count"] + 1
    assert after["active_rule_count"] == before["active_rule_count"] + 1
    assert after["firing_count"] == before["firing_count"] + 1
    assert after["total_outstanding_payout"] == pytest.approx(
        before["total_outstanding_payout"] + 7_000_000
    )


def test_horizontal_basis_risk_flag_on_zero_exposure_fixed_payout(
    client, auth_headers, make_trigger, zero_exposure_event
):
    """A fixed, blind-index rule (requires_exposed_assets=False) firing
    against an event with zero real exposure is exactly the "paid on the
    index alone" case horizontal_basis_risk_flag exists to surface."""
    tid = make_trigger(
        name="pytest-horizontal-zero-exposure",
        min_alert_level="Orange",
        requires_exposed_assets=False,
        payout_kind="fixed",
        payout_value=5_000_000,
    )
    resp = client.post(f"/parametric/evaluate/{zero_exposure_event}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    ev = _pick(resp.json()["evaluations"], tid)

    assert ev["fired"] is True
    assert ev["exposed_asset_count"] == 0
    assert ev["horizontal_basis_risk_flag"] is True
    # No modelled loss to weigh the payout against -> the whole payout reads
    # as vertical basis risk too (an "overpay on a hollow index").
    assert ev["vertical_basis_risk"] == pytest.approx(5_000_000)
    assert ev["spatial_basis_risk_pct"] is None  # fixed payout: nothing spatial to size


def test_horizontal_basis_risk_flag_when_exposure_exists_but_rule_silent(
    client, auth_headers, make_trigger, zaf_flood_hazard_id
):
    """A rule scoped to a hazard type the event isn't (TC, not FL) stays
    silent even though the event genuinely exposes assets -- real exposure,
    no payout from this instrument, the other horizontal-mismatch case."""
    tid = make_trigger(name="pytest-silent-coverage-gap", event_type="TC", min_alert_level=None)
    resp = client.post(f"/parametric/evaluate/{zaf_flood_hazard_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    ev = _pick(resp.json()["evaluations"], tid)

    assert ev["fired"] is False
    assert ev["exposed_asset_count"] > 0
    assert ev["horizontal_basis_risk_flag"] is True


def test_spatial_basis_risk_pct_zero_when_uniform_proximity(
    client, auth_headers, make_trigger, spatial_test_event
):
    """Two assets at opposite corners of a square footprint sit at the exact
    same distance from its centroid (a square's corners are equidistant from
    its center), so despite very different TIV, their proximity_score is
    identical. A tiv_share payout's naive (simple-average) and real
    (TIV-weighted) severity assumptions then coincide exactly."""
    conn = psycopg2.connect(get_settings().database_url)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO assets (asset_name, asset_type, location, building_value, contents_value)
        VALUES
          ('Corner A (large)', 'commercial', ST_GeomFromText('POINT(10 -30)', 4326), 9000000, 0),
          ('Corner B (small)', 'commercial', ST_GeomFromText('POINT(10.2 -29.8)', 4326), 500000, 0)
        RETURNING id;
        """
    )
    asset_ids = [row[0] for row in cur.fetchall()]
    conn.commit()

    try:
        tid = make_trigger(
            name="pytest-spatial-uniform",
            payout_kind="tiv_share",
            payout_value=0.1,
            min_alert_level="Orange",
        )
        resp = client.post(f"/parametric/evaluate/{spatial_test_event}", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        ev = _pick(resp.json()["evaluations"], tid)

        assert ev["fired"] is True
        assert ev["exposed_asset_count"] == 2
        assert ev["spatial_basis_risk_pct"] == pytest.approx(0.0, abs=1e-6)
    finally:
        cur.execute("DELETE FROM assets WHERE id = ANY(%s)", (asset_ids,))
        conn.commit()
        cur.close()
        conn.close()


def test_spatial_basis_risk_pct_nonzero_when_proximity_varies(
    client, auth_headers, make_trigger, spatial_test_event
):
    """A large asset at a corner (low proximity) and a small asset at the
    centroid (high proximity) pulls the TIV-weighted average proximity well
    below the simple average of the two -> the naive sizing a tiv_share
    payout implicitly assumes diverges from the real, distance-decayed loss."""
    conn = psycopg2.connect(get_settings().database_url)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO assets (asset_name, asset_type, location, building_value, contents_value)
        VALUES
          ('Corner (large, far from centroid)', 'commercial',
           ST_GeomFromText('POINT(10 -30)', 4326), 9000000, 0),
          ('Centroid (small, close)', 'commercial',
           ST_GeomFromText('POINT(10.1 -29.9)', 4326), 500000, 0)
        RETURNING id;
        """
    )
    asset_ids = [row[0] for row in cur.fetchall()]
    conn.commit()

    try:
        tid = make_trigger(
            name="pytest-spatial-varying",
            payout_kind="tiv_share",
            payout_value=0.1,
            min_alert_level="Orange",
        )
        resp = client.post(f"/parametric/evaluate/{spatial_test_event}", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        ev = _pick(resp.json()["evaluations"], tid)

        assert ev["fired"] is True
        assert ev["exposed_asset_count"] == 2
        assert ev["spatial_basis_risk_pct"] is not None
        # The large asset sits at low proximity, pulling the TIV-weighted
        # (real) severity well below the simple-average (naive) baseline --
        # comfortably outside float noise, not just nonzero in principle.
        assert ev["spatial_basis_risk_pct"] < -0.01
    finally:
        cur.execute("DELETE FROM assets WHERE id = ANY(%s)", (asset_ids,))
        conn.commit()
        cur.close()
        conn.close()


def test_evaluate_unknown_event_is_404(client, auth_headers, parametric_schema):
    resp = client.post("/parametric/evaluate/999999999", headers=auth_headers)
    assert resp.status_code == 404


def test_write_routes_require_api_key_when_configured(client, parametric_schema):
    if not get_settings().ingest_api_key:
        pytest.skip("INGEST_API_KEY not set; write routes are intentionally open")
    resp = client.post("/parametric/triggers", json={"name": "x", "payout_value": 1})
    assert resp.status_code == 401
