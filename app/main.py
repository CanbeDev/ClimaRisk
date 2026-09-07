from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db.pool import close_pool, init_pool
from app.routes.assets import router as assets_router
from app.routes.exposure import router as exposure_router
from app.routes.hazards import router as hazards_router
from app.routes.health import router as health_router
from app.routes.parametric import router as parametric_router
from app.routes.trends import router as trends_router
from app.scheduler.jobs import start_scheduler, stop_scheduler

log = logging.getLogger(__name__)


def configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    init_pool()
    start_scheduler()
    log.info("ClimRisk GDACS ingestion service started")
    try:
        yield
    finally:
        stop_scheduler()
        close_pool()
        log.info("ClimRisk GDACS ingestion service stopped")


app = FastAPI(
    title="ClimRisk GDACS Ingestion",
    description="Standalone scheduled pipeline: GDACS -> PostGIS (ZAF focus)",
    version="0.2.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(exposure_router)
app.include_router(hazards_router)
app.include_router(assets_router)
app.include_router(trends_router)
app.include_router(parametric_router)
