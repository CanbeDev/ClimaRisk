# ClimRisk — GDACS Ingestion Pipeline (Phase 1)

Standalone, scheduled ingestion service that pulls GDACS disaster data for **South Africa (ZAF)** and stores it in PostgreSQL + PostGIS.

## Architecture

- **FastAPI** — health checks and manual ingest triggers
- **APScheduler** — background polling (realtime every 2h, polygons every 6h)
- **httpx + tenacity** — GDACS HTTP client with retries
- **Shapely / GeoPandas** — geometry validation before PostGIS insert

## Setup

### 1. Database

```bash
createdb climrisk
psql climrisk -c "CREATE EXTENSION postgis;"
psql climrisk -f db/migrations/001_hazard_events.sql
psql climrisk -f db/migrations/002_ingestion_runs.sql
psql climrisk -f db/migrations/003_ingestion_errors.sql
psql climrisk -f db/migrations/004_affected_countries.sql
psql climrisk -f db/migrations/005_grant_app_role.sql
psql climrisk -f db/migrations/006_assets.sql
psql climrisk -f db/migrations/007_insured_value.sql
psql climrisk -f db/migrations/008_parametric_triggers.sql
```

Migrations `005`–`008` must be run as the table owner (e.g. `postgres`), not as `climrisk_app` —
the app role can neither grant itself access nor `CREATE TABLE`. Tables created after `005` (the
`assets` table in `006`, the parametric tables in `008`) are covered automatically by its
`ALTER DEFAULT PRIVILEGES` grant, so no further manual grant is needed for `climrisk_app` to
read/write them.

Or apply all migrations at once:

```bash
psql climrisk -f schema.sql
```

### 2. Python environment

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

### 3. Configuration

Copy `.env.example` to `.env` and set your database URL:

```
DATABASE_URL=postgresql://climrisk_app:yourpassword@localhost:5432/climrisk
GDACS_COUNTRY_FILTER=ZAF
```

Optionally set `INGEST_API_KEY` to require an `X-API-Key` header on every `/ingest/*` route and
on the `/parametric/*` write + evaluate routes (all trigger real work). Left unset, those routes
stay open — fine for local/dev use, but set this before running the service anywhere reachable
outside a trusted network.

## Running

### Scheduled service (recommended)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

APScheduler runs automatically on startup when `SCHEDULER_ENABLED=true`.

### Manual API triggers

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/db
curl -X POST http://localhost:8000/ingest/realtime
curl -X POST "http://localhost:8000/ingest/backfill?from_date=2024-01-01&to_date=2025-08-22"
curl -X POST http://localhost:8000/ingest/polygons
curl http://localhost:8000/ingest/runs
```

If `INGEST_API_KEY` is set, add `-H "X-API-Key: <your key>"` to each `/ingest/*` call above —
requests without a matching header get `401 Unauthorized`.

### CLI (backward compatible)

```bash
# Realtime poll (EVENTS4APP, ZAF filter)
python gdacs_ingest.py

# Realtime + polygon enrichment
python gdacs_ingest.py --with-polygons

# Historical backfill via SEARCH
python gdacs_ingest.py --backfill --from-date 2024-01-01 --to-date 2025-08-22
```

Run realtime first to confirm DB connectivity before backfill or polygon jobs.

## Verify

```sql
-- ZAF events by type
SELECT event_type, count(*), max(from_date)
FROM hazard_events WHERE iso3 = 'ZAF' GROUP BY event_type;

-- Footprint coverage
SELECT count(*) FILTER (WHERE footprint IS NOT NULL) AS with_polygon,
       count(*) AS total
FROM hazard_events WHERE iso3 = 'ZAF';

-- Recent ingestion runs
SELECT job_type, status, events_upserted, events_failed, started_at
FROM ingestion_runs ORDER BY started_at DESC LIMIT 10;

-- Recent errors
SELECT stage, message, created_at
FROM ingestion_errors ORDER BY created_at DESC LIMIT 10;
```

## Financial exposure metrics

`GET /exposure/intersect/{hazard_event_id}` (see [app/services/intersection.py](app/services/intersection.py))
returns, per hazard event, every asset it intersects plus:

| Field | Formula | Notes |
|---|---|---|
| `total_insured_value` | Σ TIV of intersected assets | Exposure at Risk (the ceiling) |
| `damage_ratio` | HAZUS-MH/FEMA band midpoint | Selected by hazard type + GDACS `alert_level` — see [app/services/damage_ratio.py](app/services/damage_ratio.py) |
| `probable_maximum_loss` | `total_insured_value × damage_ratio` | PML — an estimate, not TIV |
| `total_declared_insured_value` | Σ `assets.insured_value` | Assets with no declared value count as 0 (uninsured), not excluded |
| `protection_gap` | `total_insured_value − total_declared_insured_value` | |
| `protection_gap_pct` | `protection_gap / total_insured_value` | `null` when exposure is 0 |

Set `assets.insured_value` (added by migration `007`) per asset to get a meaningful Protection
Gap — it defaults to `NULL`/uninsured for every asset until declared.

## Historical / trend view

`GET /trends/hazards` (see [app/services/trends.py](app/services/trends.py)) returns every
ingested event for the configured country, oldest first, each with its exposure rolled up in a
single grouped spatial join:

| Field | Meaning |
|---|---|
| `asset_count`, `tiv_at_risk` | Assets intersecting this event's footprint, and their total TIV (0 if no footprint yet) |
| `damage_ratio`, `probable_maximum_loss` | Same HAZUS-MH/FEMA midpoint and `tiv_at_risk × damage_ratio` as `/exposure/intersect/*` |
| `declared_insured_value`, `protection_gap` | `Σ insured_value` and `tiv_at_risk − declared_insured_value` |

The dashboard's **Trends** view (top-right toggle) charts this: hazard frequency by year stacked
by type, alert-level mix by year, and TIV / PML / Protection-Gap per event over time. `recharts`
is code-split, so it only loads when that view is first opened.

## Parametric triggers (Phase 2)

Index-based cover: a rule pays a predefined amount when measurable conditions on a hazard event
are met. See [app/services/parametric.py](app/services/parametric.py). Needs migration `008`.

| Route | Purpose |
|---|---|
| `GET /parametric/triggers` | List rules (open) |
| `POST /parametric/triggers` | Create a rule (gated by `INGEST_API_KEY` if set) |
| `PATCH` / `DELETE /parametric/triggers/{id}` | Edit / remove a rule (gated) |
| `POST /parametric/evaluate/{hazard_event_id}` | Evaluate active rules against one event, persist firings (gated) |
| `POST /parametric/evaluate` | Sweep every stored event for the configured country (gated) |
| `GET /parametric/firings[?hazard_event_id=&trigger_id=]` | Current payouts + basis risk (open) |

Rule conditions (all non-null must hold): `event_type`, `min_alert_level` (Green<Orange<Red),
`min_severity_value`, `iso3`, `requires_exposed_assets`. Payout: `payout_kind` is `fixed`,
`per_asset` (× exposed asset count), or `tiv_share` (fraction × exposed TIV). Each firing records
`basis_risk = payout_amount − probable_maximum_loss` (the modelled PML from the intersection
service). With the scheduler on, active rules are re-swept every `PARAMETRIC_INTERVAL_HOURS`.

```bash
# Create a rule: any Orange+ flood that hits an insured asset pays R10m flat
curl -X POST http://localhost:8000/parametric/triggers \
  -H "Content-Type: application/json" ${INGEST_API_KEY:+-H "X-API-Key: $INGEST_API_KEY"} \
  -d '{"name":"ZAF flood – Orange","event_type":"FL","min_alert_level":"Orange",
       "requires_exposed_assets":true,"payout_kind":"fixed","payout_value":10000000}'

# Evaluate it against hazard_events.id = 4, then read the payout ledger
curl -X POST http://localhost:8000/parametric/evaluate/4 ${INGEST_API_KEY:+-H "X-API-Key: $INGEST_API_KEY"}
curl http://localhost:8000/parametric/firings?hazard_event_id=4
```

## GDACS endpoints used

| Job | Endpoint |
|---|---|
| Realtime | `GET /events/geteventlist/EVENTS4APP` (client-side ZAF filter) |
| Backfill | `GET /events/geteventlist/SEARCH?country=ZAF&eventlist=EQ;TC;FL;VO;WF;DR` |
| Polygons | `GET /polygons/getgeometry?eventtype=&eventid=&episodeid=` |

Swagger: https://www.gdacs.org/gdacsapi/swagger/index.html

## Known limitations

- **EVENTS4APP is global** — ZAF events are filtered client-side; use SEARCH backfill for history.
- **SEARCH's `country` filter is unreliable** — GDACS expects a full country name there (e.g.
  "South Africa"), not an ISO3 code, and silently returns `204 No Content` for ISO3 values
  (confirmed: this held for every country tested, not just ZAF). Backfill therefore fetches
  globally and relies on `event_affects_country()` (ISO3-based) to filter locally — the same
  logic already used for the realtime path.
- **Cyclone polygons** — the first real Polygon/MultiPolygon feature is preferred over the bare
  Point marker GDACS returns first, but TC responses interleave many per-forecast-point cone
  polygons with track LineStrings; only the first cone polygon is stored, not the full track
  corridor.
- **Rate limiting** — 0.5s delay between polygon requests, and now also between SEARCH pages;
  verify GDACS terms before scaling.
- **No SAWS yet** — GDACS only in Phase 1; add SA Weather Service as a separate ingestion path later.
