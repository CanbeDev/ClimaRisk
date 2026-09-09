"""Ingestion is worldwide; every financial/exposure view stays South-Africa-scoped.

These tests insert a synthetic foreign hazard event (Indonesia) directly into
`hazard_events` and confirm — not assume — that it is:
  * excluded from GET /hazards (default) and /trends/hazards,
  * included in GET /hazards?scope=global,
  * harmless to run_intersection() (footprint present, zero SA assets),
  * never firing a parametric rule, and absent from evaluate_all_events().
"""

from __future__ import annotations

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

# A polygon over Jakarta, nowhere near any (South African) asset.
_IDN_FOOTPRINT_WKT = "POLYGON((106.7 -6.3, 106.9 -6.3, 106.9 -6.1, 106.7 -6.1, 106.7 -6.3))"
_EVENT_TYPE = "FL"
_EVENT_ID = 999900001
_EPISODE_ID = 1


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def auth_headers() -> dict[str, str]:
    key = get_settings().ingest_api_key
    return {"X-API-Key": key} if key else {}


@pytest.fixture()
def foreign_event():
    """Insert an Indonesia flood event; yield its hazard_events.id; delete it."""
    conn = psycopg2.connect(get_settings().database_url)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO hazard_events (
            event_type, event_id, episode_id, event_name,
            alert_level, iso3, affected_countries, from_date,
            centroid, footprint
        ) VALUES (
            %s, %s, %s, 'Jakarta flood (test)',
            'Red', 'IDN', ARRAY['IDN'], now(),
            ST_SetSRID(ST_MakePoint(106.8, -6.2), 4326),
            ST_GeomFromText(%s, 4326)
        )
        ON CONFLICT (event_type, event_id, episode_id) DO UPDATE SET iso3 = EXCLUDED.iso3
        RETURNING id
        """,
        (_EVENT_TYPE, _EVENT_ID, _EPISODE_ID, _IDN_FOOTPRINT_WKT),
    )
    event_id = cur.fetchone()[0]
    conn.commit()

    yield event_id

    cur.execute("DELETE FROM hazard_events WHERE id = %s", (event_id,))
    conn.commit()
    cur.close()
    conn.close()


def _ids(feature_collection) -> set[int]:
    return {f["properties"]["hazard_event_id"] for f in feature_collection["features"]}


def test_foreign_event_excluded_from_country_hazards_included_in_global(client, foreign_event):
    country = client.get("/hazards").json()
    assert foreign_event not in _ids(country)
    assert all(f["properties"]["iso3"] != "IDN" for f in country["features"])

    world = client.get("/hazards", params={"scope": "global"}).json()
    assert foreign_event in _ids(world)
    assert len(world["features"]) > len(country["features"])


def test_foreign_event_absent_from_trends(client, foreign_event):
    events = client.get("/trends/hazards").json()["events"]
    assert all(e["hazard_event_id"] != foreign_event for e in events)


def test_intersection_on_foreign_event_is_empty_not_error(client, foreign_event):
    resp = client.get(f"/exposure/intersect/{foreign_event}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_footprint"] is True
    assert body["asset_count"] == 0
    assert body["total_insured_value"] == 0
    assert body["probable_maximum_loss"] == 0


def test_parametric_rule_never_fires_on_foreign_event(client, auth_headers, foreign_event):
    if get_settings().ingest_api_key and not auth_headers:
        pytest.skip("INGEST_API_KEY set but no header available")

    # A rule with no country override and no asset requirement — it would fire on
    # a Red flood anywhere if country weren't an implicit AND-condition.
    created = client.post(
        "/parametric/triggers",
        json={
            "name": "pytest-global-scope",
            "event_type": "FL",
            "min_alert_level": "Green",
            "requires_exposed_assets": False,
            "payout_kind": "fixed",
            "payout_value": 1_000_000,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    tid = created.json()["id"]
    try:
        result = client.post(f"/parametric/evaluate/{foreign_event}", headers=auth_headers).json()
        ours = next(e for e in result["evaluations"] if e["trigger_id"] == tid)
        assert ours["fired"] is False
        assert get_settings().gdacs_country_filter in ours["reason"]

        # Whole-portfolio sweep must not touch the foreign event at all.
        client.post("/parametric/evaluate", headers=auth_headers)
        firings = client.get(
            "/parametric/firings", params={"hazard_event_id": foreign_event}
        ).json()["firings"]
        assert firings == []
    finally:
        client.delete(f"/parametric/triggers/{tid}", headers=auth_headers)
