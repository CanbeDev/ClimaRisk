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
```

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

## GDACS endpoints used

| Job | Endpoint |
|---|---|
| Realtime | `GET /events/geteventlist/EVENTS4APP` (client-side ZAF filter) |
| Backfill | `GET /events/geteventlist/SEARCH?country=ZAF&eventlist=EQ;TC;FL;VO;WF;DR` |
| Polygons | `GET /polygons/getgeometry?eventtype=&eventid=&episodeid=` |

Swagger: https://www.gdacs.org/gdacsapi/swagger/index.html

## Known limitations

- **EVENTS4APP is global** — ZAF events are filtered client-side; use SEARCH backfill for history.
- **Cyclone polygons** — first geometry feature is stored; TC responses may include track + cone.
- **Rate limiting** — 0.5s delay between polygon requests; verify GDACS terms before scaling.
- **No SAWS yet** — GDACS only in Phase 1; add SA Weather Service as a separate ingestion path later.
