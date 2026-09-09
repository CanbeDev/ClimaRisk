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
    assert ev["basis_risk"] == pytest.approx(10_000_000 - pml)

    firings = client.get(f"/parametric/firings?hazard_event_id={zaf_flood_hazard_id}").json()["firings"]
    ours = _pick(firings, tid)
    assert ours["payout_amount"] == pytest.approx(10_000_000)
    assert ours["basis_risk"] == pytest.approx(10_000_000 - pml)


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


def test_evaluate_unknown_event_is_404(client, auth_headers, parametric_schema):
    resp = client.post("/parametric/evaluate/999999999", headers=auth_headers)
    assert resp.status_code == 404


def test_write_routes_require_api_key_when_configured(client, parametric_schema):
    if not get_settings().ingest_api_key:
        pytest.skip("INGEST_API_KEY not set; write routes are intentionally open")
    resp = client.post("/parametric/triggers", json={"name": "x", "payout_value": 1})
    assert resp.status_code == 401
