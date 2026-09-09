from __future__ import annotations

import logging
from typing import Any, Optional

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.routes.deps import require_ingest_api_key
from app.services import parametric

log = logging.getLogger(__name__)

router = APIRouter(prefix="/parametric")

# Rule writes and evaluation triggers are operational actions — gate them behind
# the same optional shared secret as /ingest/*. Reads (triggers list, firings)
# stay open like /hazards and /exposure.
_GATED = [Depends(require_ingest_api_key)]

_ALERT_LEVELS = ("Green", "Orange", "Red")


class TriggerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    is_active: bool = True
    event_type: Optional[str] = Field(default=None, max_length=8)
    min_alert_level: Optional[str] = None
    min_severity_value: Optional[float] = Field(default=None, ge=0)
    severity_unit: Optional[str] = None
    iso3: Optional[str] = Field(default=None, max_length=3)
    requires_exposed_assets: bool = True
    payout_kind: str = "fixed"
    payout_value: float = Field(ge=0)
    payout_currency: str = Field(default="ZAR", max_length=3)

    def _validate(self) -> None:
        if self.min_alert_level is not None and self.min_alert_level not in _ALERT_LEVELS:
            raise HTTPException(422, f"min_alert_level must be one of {_ALERT_LEVELS}")
        if self.payout_kind not in parametric.PAYOUT_KINDS:
            raise HTTPException(422, f"payout_kind must be one of {parametric.PAYOUT_KINDS}")
        if self.payout_kind == "tiv_share" and self.payout_value > 1:
            raise HTTPException(422, "payout_value for tiv_share is a fraction (0..1)")


class TriggerUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    event_type: Optional[str] = Field(default=None, max_length=8)
    min_alert_level: Optional[str] = None
    min_severity_value: Optional[float] = Field(default=None, ge=0)
    severity_unit: Optional[str] = None
    iso3: Optional[str] = Field(default=None, max_length=3)
    requires_exposed_assets: Optional[bool] = None
    payout_kind: Optional[str] = None
    payout_value: Optional[float] = Field(default=None, ge=0)
    payout_currency: Optional[str] = Field(default=None, max_length=3)


def _trigger_dict(t: parametric.ParametricTrigger) -> dict[str, Any]:
    return {
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "is_active": t.is_active,
        "event_type": t.event_type,
        "min_alert_level": t.min_alert_level,
        "min_severity_value": t.min_severity_value,
        "severity_unit": t.severity_unit,
        "iso3": t.iso3,
        "requires_exposed_assets": t.requires_exposed_assets,
        "payout_kind": t.payout_kind,
        "payout_value": t.payout_value,
        "payout_currency": t.payout_currency,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _evaluation_dict(e: parametric.TriggerEvaluation) -> dict[str, Any]:
    return {
        "trigger_id": e.trigger_id,
        "trigger_name": e.trigger_name,
        "hazard_event_id": e.hazard_event_id,
        "fired": e.fired,
        "reason": e.reason,
        "exposed_asset_count": e.exposed_asset_count,
        "exposed_tiv": e.exposed_tiv,
        "modelled_loss": e.modelled_loss,
        "payout_amount": e.payout_amount,
        "basis_risk": e.basis_risk,
        "basis_risk_pct": e.basis_risk_pct,
        "payout_currency": e.payout_currency,
    }


def _read_or_500(fn, what: str):
    """Run a read and translate a DB error into a clean 500 (real error logged
    server-side, not leaked) — the same convention as exposure.py."""
    try:
        return fn()
    except psycopg2.Error as exc:
        log.exception("Database error %s", what)
        raise HTTPException(status_code=500, detail=f"Database error {what}") from exc


@router.get("/summary")
def get_summary() -> dict[str, Any]:
    return _read_or_500(parametric.summary, "building parametric summary")


@router.get("/triggers")
def list_triggers(active_only: bool = Query(default=False)) -> dict[str, Any]:
    triggers = _read_or_500(
        lambda: parametric.list_triggers(active_only=active_only), "listing triggers"
    )
    return {"triggers": [_trigger_dict(t) for t in triggers]}


@router.get("/triggers/{trigger_id}")
def get_trigger(trigger_id: int) -> dict[str, Any]:
    try:
        return _trigger_dict(_read_or_500(lambda: parametric.get_trigger(trigger_id), "loading trigger"))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/triggers", dependencies=_GATED, status_code=201)
def create_trigger(body: TriggerCreate) -> dict[str, Any]:
    body._validate()
    try:
        return _trigger_dict(parametric.create_trigger(body.model_dump()))
    except psycopg2.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail=f"A trigger named {body.name!r} already exists") from exc
    except psycopg2.Error as exc:
        log.exception("Database error creating parametric trigger")
        raise HTTPException(status_code=500, detail="Database error creating trigger") from exc


@router.patch("/triggers/{trigger_id}", dependencies=_GATED)
def update_trigger(trigger_id: int, body: TriggerUpdate) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if "min_alert_level" in changes and changes["min_alert_level"] not in _ALERT_LEVELS:
        raise HTTPException(422, f"min_alert_level must be one of {_ALERT_LEVELS}")
    if "payout_kind" in changes and changes["payout_kind"] not in parametric.PAYOUT_KINDS:
        raise HTTPException(422, f"payout_kind must be one of {parametric.PAYOUT_KINDS}")
    try:
        return _trigger_dict(parametric.update_trigger(trigger_id, changes))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except psycopg2.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="A trigger with that name already exists") from exc
    except psycopg2.Error as exc:
        log.exception("Database error updating parametric trigger id=%s", trigger_id)
        raise HTTPException(status_code=500, detail="Database error updating trigger") from exc


@router.delete("/triggers/{trigger_id}", dependencies=_GATED, status_code=204)
def delete_trigger(trigger_id: int) -> None:
    try:
        parametric.delete_trigger(trigger_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/evaluate/{hazard_event_id}", dependencies=_GATED)
def evaluate_event(hazard_event_id: int) -> dict[str, Any]:
    try:
        evaluations = parametric.evaluate_event(hazard_event_id, persist=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except psycopg2.Error as exc:
        log.exception("Database error evaluating triggers for hazard_event_id=%s", hazard_event_id)
        raise HTTPException(status_code=500, detail="Database error evaluating triggers") from exc

    fired = [e for e in evaluations if e.fired]
    return {
        "hazard_event_id": hazard_event_id,
        "evaluated": len(evaluations),
        "fired": len(fired),
        "total_payout": sum(e.payout_amount for e in fired),
        "evaluations": [_evaluation_dict(e) for e in evaluations],
    }


@router.post("/evaluate", dependencies=_GATED)
def evaluate_all() -> dict[str, Any]:
    try:
        return parametric.evaluate_all_events()
    except psycopg2.Error as exc:
        log.exception("Database error during parametric sweep")
        raise HTTPException(status_code=500, detail="Database error during parametric sweep") from exc


@router.get("/firings")
def list_firings(
    hazard_event_id: Optional[int] = Query(default=None),
    trigger_id: Optional[int] = Query(default=None),
) -> dict[str, Any]:
    firings = _read_or_500(
        lambda: parametric.list_firings(hazard_event_id=hazard_event_id, trigger_id=trigger_id),
        "listing firings",
    )
    return {
        "count": len(firings),
        "total_payout": sum(f["payout_amount"] for f in firings),
        "firings": firings,
    }
