from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.config import get_settings
from app.db.pool import close_pool, init_pool
from app.routes.health import router
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

app.include_router(router)
