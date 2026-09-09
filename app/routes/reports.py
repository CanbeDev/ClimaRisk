from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

import psycopg2
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.services.disclosure import build_disclosure_report, render_html

log = logging.getLogger(__name__)

router = APIRouter(prefix="/reports")

_FROM = Query(default=None, alias="from", description="Reporting period start (YYYY-MM-DD)")
_TO = Query(default=None, alias="to", description="Reporting period end (YYYY-MM-DD)")


def _build(from_date: Optional[date], to_date: Optional[date]):
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="'from' must not be after 'to'")
    try:
        return build_disclosure_report(period_start=from_date, period_end=to_date)
    except psycopg2.Error as exc:
        log.exception("Database error building disclosure report")
        raise HTTPException(status_code=500, detail="Database error building disclosure report") from exc


@router.get("/disclosure")
def disclosure_json(
    from_date: Optional[date] = _FROM,
    to_date: Optional[date] = _TO,
) -> dict[str, Any]:
    return _build(from_date, to_date).to_dict()


@router.get("/disclosure.html", response_class=HTMLResponse)
def disclosure_html(
    from_date: Optional[date] = _FROM,
    to_date: Optional[date] = _TO,
) -> HTMLResponse:
    return HTMLResponse(render_html(_build(from_date, to_date)))
