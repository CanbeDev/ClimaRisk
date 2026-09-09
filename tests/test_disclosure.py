"""Tests for the climate disclosure report (Step 8 / Phase 3).

Integration tests against the real database via DATABASE_URL, same style as the
other suites.
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
    /exposure/intersect for the same event."""
    report = client.get("/reports/disclosure").json()
    firing = [e for e in report["hazard_exposure"]["events"] if e["asset_count"] > 0]
    if not firing:
        pytest.skip("no firing events in the demo dataset")

    e = firing[0]
    direct = client.get(f"/exposure/intersect/{e['hazard_event_id']}").json()
    assert e["probable_maximum_loss"] == pytest.approx(direct["probable_maximum_loss"])
    assert e["tiv_at_risk"] == pytest.approx(direct["total_insured_value"])


def test_disclosure_html_renders(client):
    resp = client.get("/reports/disclosure.html")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    html = resp.text
    assert get_settings().report_org_name in html
    assert "Methodology" in html
    assert "<h2>" in html
