# ClimRisk

**A South Africa–focused climate hazard exposure platform.** ClimRisk ingests live disaster
data from [GDACS](https://www.gdacs.org/), stores hazard footprints in PostGIS, intersects them
against a portfolio of insured assets, and reports the financial exposure — Total Insured Value
at risk, Probable Maximum Loss, Protection Gap, business-interruption loss. On top of that sits
a parametric trigger engine that decides which index-based insurance rules pay out for a given
event and by how much, and a TCFD-style disclosure report that rolls it all up for a reporting
period.

It is three deployable pieces that share one database and nothing else:

| Piece | What it is | Code |
|---|---|---|
| **Ingestion service** | Scheduled + on-demand GDACS → PostGIS pipeline (realtime feed, historical backfill, polygon enrichment) | `app/gdacs`, `app/ingestion`, `app/scheduler` |
| **Query API** | FastAPI read/write service: spatial-financial exposure, trend series, parametric rules, disclosure report | `app/routes`, `app/services` |
| **Dashboard** | Static React + Leaflet SPA: map, financial metrics, historical trends, parametric rules & ledger, disclosure report | `frontend/` |

The design rationale — why hand-written SQL over an ORM, why ingestion stores the world but
every financial view scopes to South Africa in SQL, why the damage ratio is a documented
approximation, why `trigger_firings` is a live ledger rather than a log — is in
**[docs/architecture.md](docs/architecture.md)**.

## Stack

- **Backend** — FastAPI, psycopg2 + PostgreSQL/PostGIS, APScheduler (background polling),
  httpx + tenacity (retrying GDACS client), Shapely/GeoPandas (geometry validation),
  pydantic-settings
- **Frontend** — Vite, React 19, Tailwind v4, react-leaflet, recharts (code-split), lucide-react
- **Tests** — pytest, integration-style against a real database

## Project status

Against the ClimRisk Master Document build order:

| Step | Feature | Status |
|---|---|---|
| 1 | GDACS → PostGIS pipeline, scheduled | ✅ Done |
| 2 | Asset / exposure model | ✅ Done |
| 3 | Spatial intersection (footprint → exposed assets), tested | ✅ Done |
| 4 | Map interface | ✅ Done |
| 5 | Financial dashboard: Exposure, BI loss, PML, Protection Gap | ✅ Done |
| 6 | Historical / trend view | ✅ Done |
| 7 | Parametric trigger rules engine (Phase 2) | ✅ Done |
| 8 | Climate disclosure report export (Phase 3) | ✅ Done |

---

## Setup

### 1. Database

```bash
createdb climrisk
psql climrisk -c "CREATE EXTENSION postgis;"
psql climrisk -f schema.sql          # runs every migration in order
```

Or apply migrations individually from `db/migrations/` (`001` … `009`).

> **Migrations `005`–`009` must be run as the table owner** (e.g. `postgres`), not as
> `climrisk_app` — the app role can neither grant itself access, `CREATE TABLE`, nor
> `CREATE`/`DROP INDEX`. `005` grants `climrisk_app` read/write on existing tables **and** sets
> `ALTER DEFAULT PRIVILEGES`, so tables created by later migrations (`assets` in `006`, the
> parametric tables in `008`) inherit the grant automatically when applied by that same owner.
> `009` is an index-only adjustment for worldwide event volume.

### 2. Backend

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (source .venv/bin/activate elsewhere)
pip install -r requirements.txt

cp .env.example .env            # then edit DATABASE_URL etc.
```

Key settings (`.env`):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | `postgresql://climrisk_app:pw@localhost:5432/climrisk` |
| `GDACS_COUNTRY_FILTER` | ISO3 code the whole system scopes to (default `ZAF`) |
| `SCHEDULER_ENABLED` | Run the background polling jobs on startup (default `true`) |
| `INGEST_API_KEY` | If set, `/ingest/*` and `/parametric/*` write + evaluate routes require a matching `X-API-Key` header. Unset = open (local/dev only). |
| `PARAMETRIC_AUTO_EVALUATE`, `PARAMETRIC_INTERVAL_HOURS` | Scheduled re-evaluation of active trigger rules (default on, every 6h) |
| `REPORT_ORG_NAME` | Name printed on the disclosure report (default `ClimRisk Demo Portfolio`) |

### 3. Frontend

```bash
cd frontend
npm install
# frontend/.env sets VITE_API_BASE_URL (default http://localhost:8000)
```

---

## Running

### Backend service

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

APScheduler starts automatically when `SCHEDULER_ENABLED=true` (realtime poll every 2h, polygon
enrichment every 6h, parametric sweep every 6h). Interactive API docs at `/docs`.

### Dashboard

```bash
cd frontend
npm run dev            # http://localhost:5173
npm run build          # static bundle in frontend/dist/
```

### Ingestion — manual triggers

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/db
curl -X POST http://localhost:8000/ingest/realtime
curl -X POST "http://localhost:8000/ingest/backfill?from_date=2024-01-01&to_date=2025-08-22"
curl -X POST http://localhost:8000/ingest/polygons
curl http://localhost:8000/ingest/runs
```

If `INGEST_API_KEY` is set, add `-H "X-API-Key: <key>"` to each — without it these return `401`.

### Ingestion — CLI (backward compatible)

```bash
python gdacs_ingest.py                                             # realtime poll (EVENTS4APP, ZAF filter)
python gdacs_ingest.py --with-polygons                             # realtime + polygon enrichment
python gdacs_ingest.py --backfill --from-date 2024-01-01 --to-date 2025-08-22   # historical via SEARCH
```

Run realtime first to confirm DB connectivity before backfill or polygon jobs.

### Tests

```bash
pytest -q
```

Integration tests run against the database in `DATABASE_URL` (no mocking). They reuse a real
ingested event and assert on the *delta* their own inserts cause, so existing data doesn't break
them. `tests/test_parametric.py` skips cleanly if migration `008` hasn't been applied.

---

## API reference

### Exposure — `GET /exposure/intersect/{hazard_event_id}`

Every asset whose location intersects the event footprint, plus:

| Field | Formula | Notes |
|---|---|---|
| `total_insured_value` | Σ TIV of intersected assets | Exposure at Risk (the ceiling) |
| `damage_ratio` | HAZUS-MH/FEMA band midpoint | By hazard type + GDACS `alert_level` — see [`app/services/damage_ratio.py`](app/services/damage_ratio.py) |
| `probable_maximum_loss` | `total_insured_value × damage_ratio` | PML — an estimate, not TIV |
| `total_declared_insured_value` | Σ `assets.insured_value` | Assets with no declared value count as `0` (uninsured), not excluded |
| `protection_gap` | `total_insured_value − total_declared_insured_value` | |
| `protection_gap_pct` | `protection_gap / total_insured_value` | `null` when exposure is `0` |

Business-interruption loss is computed on the frontend against full TIV (the ceiling), shown
alongside PML rather than conflated with it.

### Trends — `GET /trends/hazards`

Every ingested event for the configured country, oldest first, exposure rolled up in one grouped
spatial join: `asset_count`, `tiv_at_risk`, `damage_ratio`, `probable_maximum_loss`,
`declared_insured_value`, `protection_gap`. The dashboard's **Trends** view charts hazard
frequency by year (stacked by type), alert-level mix by year, and TIV / PML / Protection-Gap per
event over time.

### Parametric triggers — `/parametric/*`

Index-based cover: a rule pays a predefined amount when measurable conditions on a hazard event
are met. See [`app/services/parametric.py`](app/services/parametric.py). Driven by the
**Parametric** view in the dashboard (third top-level toggle) — rule table, create form,
payout ledger, and a "re-evaluate all events" action.

| Route | Purpose | Auth |
|---|---|---|
| `GET /parametric/summary` | Rule counts + total outstanding payout + net basis risk | open |
| `GET /parametric/triggers` | List rules | open |
| `POST /parametric/triggers` | Create a rule | gated |
| `PATCH` / `DELETE /parametric/triggers/{id}` | Edit / remove a rule | gated |
| `POST /parametric/evaluate/{hazard_event_id}` | Evaluate active rules against one event, persist firings | gated |
| `POST /parametric/evaluate` | Sweep every stored event for the configured country | gated |
| `GET /parametric/firings[?hazard_event_id=&trigger_id=]` | Current payouts + basis risk | open |

Rule conditions (every non-null one must hold): `event_type`, `min_alert_level`
(`Green` < `Orange` < `Red`), `min_severity_value`, `iso3`, `requires_exposed_assets`.
Payout `payout_kind`: `fixed` (flat), `per_asset` (× exposed asset count), `tiv_share`
(fraction × exposed TIV). Each firing records
`basis_risk = payout_amount − probable_maximum_loss` — the signed gap between the parametric
payout and the modelled loss (positive = the policy overpays for that event). `trigger_firings`
is a **live ledger**: a rule's row is removed when it stops firing on re-evaluation, or when the
rule is deactivated or deleted.

The dashboard sends the operator's `X-API-Key` (kept in `localStorage`) only on the gated calls;
the CORS config allows `GET`, `POST`, `PATCH`, `DELETE` from the dev-server origins.

```bash
# A rule: any Orange+ flood that hits an insured asset pays R10m flat
curl -X POST http://localhost:8000/parametric/triggers \
  -H "Content-Type: application/json" ${INGEST_API_KEY:+-H "X-API-Key: $INGEST_API_KEY"} \
  -d '{"name":"ZAF flood - Orange","event_type":"FL","min_alert_level":"Orange",
       "requires_exposed_assets":true,"payout_kind":"fixed","payout_value":10000000}'

# Evaluate against hazard_events.id = 4, then read the payout ledger
curl -X POST http://localhost:8000/parametric/evaluate/4 ${INGEST_API_KEY:+-H "X-API-Key: $INGEST_API_KEY"}
curl "http://localhost:8000/parametric/firings?hazard_event_id=4"
```

### Climate disclosure report — `/reports/*` (Phase 3)

A TCFD-style report for a reporting period: portfolio totals, per-event exposure (TIV at risk,
PML, protection gap), the parametric position, and a methodology & limitations section. See
[`app/services/disclosure.py`](app/services/disclosure.py). Reached from the **Report** view in
the dashboard (period pickers + inline preview + a "Printable report" button).

| Route | Returns |
|---|---|
| `GET /reports/disclosure[?from=&to=]` | Structured JSON |
| `GET /reports/disclosure.html[?from=&to=]` | Self-contained print-styled HTML (browser → PDF) |

`from` / `to` are `YYYY-MM-DD`; unset, the period spans the first stored event to today. The
report is rebuilt live per request (not stored), and reuses the same trend + parametric services
so its numbers match the other views. Set `REPORT_ORG_NAME` for the printed heading.

```bash
curl "http://localhost:8000/reports/disclosure?from=2022-01-01&to=2022-12-31"
# open the printable version in a browser and Ctrl-P → Save as PDF
```

### Map data

`GET /hazards` and `GET /assets` return GeoJSON `FeatureCollection`s — consumed directly by
`react-leaflet`'s `<GeoJSON>`, no translation layer.

---

## Verify (SQL)

```sql
-- ZAF events by type
SELECT event_type, count(*), max(from_date)
FROM hazard_events WHERE iso3 = 'ZAF' GROUP BY event_type;

-- Footprint coverage
SELECT count(*) FILTER (WHERE footprint IS NOT NULL) AS with_polygon, count(*) AS total
FROM hazard_events WHERE iso3 = 'ZAF';

-- Recent ingestion runs / errors
SELECT job_type, status, events_upserted, events_failed, started_at
FROM ingestion_runs ORDER BY started_at DESC LIMIT 10;

SELECT stage, message, created_at
FROM ingestion_errors ORDER BY created_at DESC LIMIT 10;

-- Outstanding parametric payouts
SELECT t.name, f.payout_amount, f.basis_risk, f.evaluated_at
FROM trigger_firings f JOIN parametric_triggers t ON t.id = f.trigger_id
ORDER BY f.evaluated_at DESC;
```

## GDACS endpoints used

| Job | Endpoint |
|---|---|
| Realtime | `GET /events/geteventlist/EVENTS4APP` (worldwide feed, stored as-is) |
| Backfill | `GET /events/geteventlist/SEARCH` (worldwide; `country` param unusable — see below) |
| Polygons | `GET /polygons/getgeometry?eventtype=&eventid=&episodeid=` (country-scoped) |

Swagger: <https://www.gdacs.org/gdacsapi/swagger/index.html>

## Known limitations

- **Ingestion is worldwide; the product is South Africa** — `hazard_events` stores every GDACS
  event regardless of country. Assets are SA-only and every financial/exposure query is
  country-scoped in SQL (`/hazards` default, `/trends/hazards`, `/exposure/*`, `/reports/*`,
  parametric evaluation), so a flood in Indonesia is stored but never appears in a SA view.
  `GET /hazards?scope=global` returns the unfiltered worldwide set for the 3D globe view.
- **SEARCH's `country` filter is unreliable** — GDACS expects a full country name there (e.g.
  "South Africa"), not an ISO3 code, and silently returns `204 No Content` for ISO3 values
  (confirmed across multiple countries). It is not sent; the SEARCH feed is consumed globally.
- **Polygon enrichment stays country-scoped** — the 6h geometry job only fetches footprints for
  events affecting `GDACS_COUNTRY_FILTER`, so its workload does not grow with global ingestion.
  If it is ever made global, the cadence + GDACS rate limits would need a ZAF-first priority
  pass — see `docs/followup-items.txt` #5.
- **Cyclone footprints are one cone segment, not a track corridor** — TC geometry responses
  interleave many per-forecast-point cone polygons with track LineStrings; only the first cone
  polygon is stored.
- **PML uses a documented approximation** — a HAZUS-MH/FEMA band midpoint selected by GDACS
  `alert_level`, not hazard-specific severity (flood depth, cyclone category). Parametric
  `basis_risk` is measured against this modelled PML, since there is no ground-truth loss feed.
- **Read routes have no auth** — only `/ingest/*` and `/parametric/*` writes are gated
  (optionally). Put the service behind network-level restriction before exposing it.
- **No SAWS yet** — GDACS is the only hazard source; South African Weather Service integration
  is a later phase.

## Repository layout

```
app/
  gdacs/        GDACS HTTP client, response models, feature parser
  ingestion/    realtime / backfill / polygon-enrichment jobs
  scheduler/    APScheduler wiring
  db/           connection pool, hand-written SQL repository
  services/     intersection, damage_ratio, trends, parametric (the engine layer)
  routes/       one FastAPI APIRouter per domain
db/migrations/  numbered, idempotent SQL
docs/           architecture.md — the decision record
frontend/       Vite + React dashboard
tests/          pytest integration tests
```
