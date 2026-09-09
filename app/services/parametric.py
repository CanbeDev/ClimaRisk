"""Parametric trigger rules engine (Build Order Step 7 / Phase 2).

Parametric cover pays a *predefined* amount when a *measurable* condition on a
hazard event is met — there is no loss adjustment. This module holds:

  * the rule model (`ParametricTrigger`) and CRUD over `parametric_triggers`,
  * the evaluator: given a `hazard_events.id`, decide which active rules fire,
    size each payout, and record the **basis risk** — the signed gap between
    the parametric payout and the modelled PML loss from
    `app/services/intersection.py` (positive = the policy overpays for this
    event, negative = it underpays).

Design choices (why it looks like this):

  * **Conditions are a fixed AND-set of columns, not an expression language.**
    Every non-NULL condition on a rule must hold. The inputs are exactly the
    fields ClimRisk already trusts on `hazard_events` (`event_type`,
    `alert_level`, `severity_value`, country) plus "does the footprint touch
    the portfolio". A DSL would be more flexible and much harder to reason
    about for a demo with a handful of rules.

  * **Payout leans on the intersection service, not a second spatial query.**
    `per_asset` and `tiv_share` payouts, and the `requires_exposed_assets`
    gate, all read `run_intersection()`'s result — computed once per event and
    shared across every rule that needs it.

  * **`trigger_firings` stores only rules that currently fire.** A rule that
    stops firing on re-evaluation has its row deleted, so the table is a live
    payout ledger. Non-firing evaluations are returned to the caller (with a
    `reason`) but not persisted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import psycopg2

from app.config import Settings, get_settings
from app.db.pool import get_connection
from app.services.intersection import IntersectionResult, run_intersection

log = logging.getLogger(__name__)

# GDACS alert levels as an ordinal floor. Green < Orange < Red.
_ALERT_ORDINAL = {"Green": 1, "Orange": 2, "Red": 3}

PAYOUT_KINDS = ("fixed", "per_asset", "tiv_share")


@dataclass
class ParametricTrigger:
    id: int
    name: str
    description: Optional[str]
    is_active: bool
    event_type: Optional[str]
    min_alert_level: Optional[str]
    min_severity_value: Optional[float]
    severity_unit: Optional[str]
    iso3: Optional[str]
    requires_exposed_assets: bool
    payout_kind: str
    payout_value: float
    payout_currency: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def needs_exposure(self) -> bool:
        """Whether evaluating this rule requires the intersection result."""
        return self.requires_exposed_assets or self.payout_kind in ("per_asset", "tiv_share")


@dataclass
class TriggerEvaluation:
    trigger_id: int
    trigger_name: str
    hazard_event_id: int
    fired: bool
    reason: str
    exposed_asset_count: int
    exposed_tiv: float
    modelled_loss: float
    payout_amount: float
    basis_risk: float
    payout_currency: str

    @property
    def basis_risk_pct(self) -> Optional[float]:
        """Basis risk as a fraction of the modelled loss. None when there is no
        modelled loss to compare against (a pure index payout on an event that
        exposed nothing) — the ratio is undefined, not 0."""
        if self.modelled_loss <= 0:
            return None
        return self.basis_risk / self.modelled_loss


# --------------------------------------------------------------------------- #
# Row mapping
# --------------------------------------------------------------------------- #

_TRIGGER_COLUMNS = """
    id, name, description, is_active, event_type, min_alert_level,
    min_severity_value, severity_unit, iso3, requires_exposed_assets,
    payout_kind, payout_value, payout_currency, created_at, updated_at
"""


def _row_to_trigger(row) -> ParametricTrigger:
    return ParametricTrigger(
        id=row[0],
        name=row[1],
        description=row[2],
        is_active=row[3],
        event_type=row[4],
        min_alert_level=row[5],
        min_severity_value=float(row[6]) if row[6] is not None else None,
        severity_unit=row[7],
        iso3=row[8],
        requires_exposed_assets=row[9],
        payout_kind=row[10],
        payout_value=float(row[11]),
        payout_currency=row[12],
        created_at=row[13],
        updated_at=row[14],
    )


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #

_ALLOWED_UPDATE_FIELDS = {
    "name",
    "description",
    "is_active",
    "event_type",
    "min_alert_level",
    "min_severity_value",
    "severity_unit",
    "iso3",
    "requires_exposed_assets",
    "payout_kind",
    "payout_value",
    "payout_currency",
}


def list_triggers(active_only: bool = False) -> list[ParametricTrigger]:
    where = "WHERE is_active" if active_only else ""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_TRIGGER_COLUMNS} FROM parametric_triggers {where} ORDER BY id")
            return [_row_to_trigger(r) for r in cur.fetchall()]


def get_trigger(trigger_id: int) -> ParametricTrigger:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_TRIGGER_COLUMNS} FROM parametric_triggers WHERE id = %s",
                (trigger_id,),
            )
            row = cur.fetchone()
    if row is None:
        raise ValueError(f"No parametric_triggers row with id={trigger_id}")
    return _row_to_trigger(row)


def create_trigger(data: dict) -> ParametricTrigger:
    """Insert a rule. `data` is validated by the API layer's Pydantic model;
    this trusts the keys it's given and lets the DB CHECK constraints and the
    UNIQUE(name) index be the final gate (a duplicate name raises
    psycopg2.errors.UniqueViolation, which the route maps to 409)."""
    cols = [
        "name", "description", "is_active", "event_type", "min_alert_level",
        "min_severity_value", "severity_unit", "iso3", "requires_exposed_assets",
        "payout_kind", "payout_value", "payout_currency",
    ]
    values = [data.get(c) for c in cols]
    placeholders = ", ".join(["%s"] * len(cols))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO parametric_triggers ({', '.join(cols)}) "
                f"VALUES ({placeholders}) RETURNING {_TRIGGER_COLUMNS}",
                values,
            )
            row = cur.fetchone()
        conn.commit()
    log.info("Created parametric trigger id=%s name=%s", row[0], row[1])
    return _row_to_trigger(row)


def update_trigger(trigger_id: int, changes: dict) -> ParametricTrigger:
    fields = {k: v for k, v in changes.items() if k in _ALLOWED_UPDATE_FIELDS}
    if not fields:
        return get_trigger(trigger_id)
    set_sql = ", ".join(f"{k} = %s" for k in fields)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE parametric_triggers SET {set_sql}, updated_at = now() "
                f"WHERE id = %s RETURNING {_TRIGGER_COLUMNS}",
                [*fields.values(), trigger_id],
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"No parametric_triggers row with id={trigger_id}")
            # A deactivated rule is never re-evaluated, so its firings would
            # otherwise linger in the ledger forever. Clear them now so the
            # ledger stays "what currently pays out".
            if fields.get("is_active") is False:
                cur.execute("DELETE FROM trigger_firings WHERE trigger_id = %s", (trigger_id,))
        conn.commit()
    log.info("Updated parametric trigger id=%s fields=%s", trigger_id, sorted(fields))
    return _row_to_trigger(row)


def delete_trigger(trigger_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM parametric_triggers WHERE id = %s", (trigger_id,))
            deleted = cur.rowcount
        conn.commit()
    if not deleted:
        raise ValueError(f"No parametric_triggers row with id={trigger_id}")
    log.info("Deleted parametric trigger id=%s (firings cascade)", trigger_id)


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #

@dataclass
class _EventFacts:
    hazard_event_id: int
    event_type: str
    alert_level: Optional[str]
    severity_value: Optional[float]
    iso3: Optional[str]
    affected_countries: list[str]
    has_footprint: bool


def _fetch_event_facts(conn, hazard_event_id: int) -> Optional[_EventFacts]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, event_type, alert_level, severity_value, iso3,
                   COALESCE(affected_countries, '{}'), footprint IS NOT NULL
            FROM hazard_events WHERE id = %s
            """,
            (hazard_event_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return _EventFacts(
        hazard_event_id=row[0],
        event_type=row[1],
        alert_level=row[2],
        severity_value=float(row[3]) if row[3] is not None else None,
        iso3=row[4],
        affected_countries=list(row[5]) if row[5] else [],
        has_footprint=row[6],
    )


def _check_conditions(
    trigger: ParametricTrigger,
    facts: _EventFacts,
    exposure: Optional[IntersectionResult],
    default_iso3: str,
) -> tuple[bool, str]:
    """Return (fired, reason). Every non-NULL condition on the rule must hold."""
    if trigger.event_type and trigger.event_type != facts.event_type:
        return False, f"event_type {facts.event_type} != required {trigger.event_type}"

    if trigger.min_alert_level:
        have = _ALERT_ORDINAL.get(facts.alert_level or "", 0)
        need = _ALERT_ORDINAL[trigger.min_alert_level]
        if have < need:
            return False, (
                f"alert_level {facts.alert_level or 'none'} below required {trigger.min_alert_level}"
            )

    if trigger.min_severity_value is not None:
        if facts.severity_value is None:
            return False, "no severity_value on event; rule requires a minimum"
        if facts.severity_value < trigger.min_severity_value:
            return False, (
                f"severity_value {facts.severity_value} below required {trigger.min_severity_value}"
            )

    required_iso3 = trigger.iso3 or default_iso3
    if required_iso3 not in ({facts.iso3} | set(facts.affected_countries)):
        return False, f"event does not affect {required_iso3}"

    if trigger.requires_exposed_assets:
        if exposure is None or exposure.asset_count == 0:
            return False, "no insured assets intersect the event footprint"

    return True, "all conditions met"


def _size_payout(trigger: ParametricTrigger, exposure: Optional[IntersectionResult]) -> float:
    if trigger.payout_kind == "fixed":
        return trigger.payout_value
    if exposure is None:
        return 0.0
    if trigger.payout_kind == "per_asset":
        return trigger.payout_value * exposure.asset_count
    if trigger.payout_kind == "tiv_share":
        return trigger.payout_value * exposure.total_insured_value
    log.warning("Unknown payout_kind=%s on trigger id=%s; paying 0", trigger.payout_kind, trigger.id)
    return 0.0


def evaluate_event(
    hazard_event_id: int,
    settings: Optional[Settings] = None,
    persist: bool = True,
) -> list[TriggerEvaluation]:
    """Evaluate every active rule against one hazard event.

    Returns one `TriggerEvaluation` per active rule (fired or not, with a
    reason). When `persist` is True, fired rules are upserted into
    `trigger_firings` and rules that no longer fire have their row removed.
    Raises `ValueError` for an unknown `hazard_event_id`.
    """
    settings = settings or get_settings()
    default_iso3 = settings.gdacs_country_filter

    with get_connection() as conn:
        facts = _fetch_event_facts(conn, hazard_event_id)
        if facts is None:
            raise ValueError(f"No hazard_events row with id={hazard_event_id}")
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_TRIGGER_COLUMNS} FROM parametric_triggers WHERE is_active ORDER BY id"
            )
            triggers = [_row_to_trigger(r) for r in cur.fetchall()]

    if not triggers:
        log.info("No active parametric triggers; nothing to evaluate for event id=%s", hazard_event_id)
        return []

    # One shared intersection result for every rule that needs exposure data.
    exposure: Optional[IntersectionResult] = None
    if any(t.needs_exposure() for t in triggers):
        exposure = run_intersection(hazard_event_id, settings=settings)

    modelled_loss = exposure.probable_maximum_loss if exposure else 0.0
    exposed_count = exposure.asset_count if exposure else 0
    exposed_tiv = exposure.total_insured_value if exposure else 0.0

    evaluations: list[TriggerEvaluation] = []
    for trigger in triggers:
        fired, reason = _check_conditions(trigger, facts, exposure, default_iso3)
        payout = _size_payout(trigger, exposure) if fired else 0.0
        evaluations.append(
            TriggerEvaluation(
                trigger_id=trigger.id,
                trigger_name=trigger.name,
                hazard_event_id=hazard_event_id,
                fired=fired,
                reason=reason,
                exposed_asset_count=exposed_count,
                exposed_tiv=exposed_tiv,
                modelled_loss=modelled_loss,
                payout_amount=payout,
                # Basis risk only means something once the rule pays out; a rule
                # that didn't fire has no payout to compare against the loss.
                basis_risk=(payout - modelled_loss) if fired else 0.0,
                payout_currency=trigger.payout_currency,
            )
        )

    if persist:
        _persist_evaluations(hazard_event_id, evaluations)

    fired_n = sum(1 for e in evaluations if e.fired)
    log.info(
        "Evaluated %d active trigger(s) for hazard_events.id=%s: %d fired, total payout=%.2f",
        len(evaluations),
        hazard_event_id,
        fired_n,
        sum(e.payout_amount for e in evaluations if e.fired),
    )
    return evaluations


def _persist_evaluations(hazard_event_id: int, evaluations: list[TriggerEvaluation]) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            for ev in evaluations:
                if ev.fired:
                    cur.execute(
                        """
                        INSERT INTO trigger_firings (
                            trigger_id, hazard_event_id, reason,
                            exposed_asset_count, exposed_tiv, modelled_loss,
                            payout_amount, basis_risk, payout_currency, evaluated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                        ON CONFLICT (trigger_id, hazard_event_id) DO UPDATE SET
                            reason              = EXCLUDED.reason,
                            exposed_asset_count = EXCLUDED.exposed_asset_count,
                            exposed_tiv         = EXCLUDED.exposed_tiv,
                            modelled_loss       = EXCLUDED.modelled_loss,
                            payout_amount       = EXCLUDED.payout_amount,
                            basis_risk          = EXCLUDED.basis_risk,
                            payout_currency     = EXCLUDED.payout_currency,
                            evaluated_at        = now()
                        """,
                        (
                            ev.trigger_id,
                            ev.hazard_event_id,
                            ev.reason,
                            ev.exposed_asset_count,
                            ev.exposed_tiv,
                            ev.modelled_loss,
                            ev.payout_amount,
                            ev.basis_risk,
                            ev.payout_currency,
                        ),
                    )
                else:
                    # A rule that no longer fires must not leave a stale payout row.
                    cur.execute(
                        "DELETE FROM trigger_firings WHERE trigger_id = %s AND hazard_event_id = %s",
                        (ev.trigger_id, ev.hazard_event_id),
                    )
        conn.commit()


def evaluate_all_events(settings: Optional[Settings] = None) -> dict:
    """Evaluate active rules against every hazard event for the configured
    country. Used by the scheduled job and the batch endpoint."""
    settings = settings or get_settings()
    country = settings.gdacs_country_filter

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM hazard_events
                WHERE iso3 = %s OR %s = ANY(affected_countries)
                ORDER BY from_date ASC NULLS LAST
                """,
                (country, country),
            )
            event_ids = [r[0] for r in cur.fetchall()]

    events_evaluated = 0
    firings = 0
    total_payout = 0.0
    for event_id in event_ids:
        try:
            evals = evaluate_event(event_id, settings=settings, persist=True)
        except psycopg2.Error:
            log.exception("Parametric evaluation failed for hazard_events.id=%s", event_id)
            continue
        events_evaluated += 1
        firings += sum(1 for e in evals if e.fired)
        total_payout += sum(e.payout_amount for e in evals if e.fired)

    summary = {
        "events_evaluated": events_evaluated,
        "events_total": len(event_ids),
        "firings": firings,
        "total_payout": total_payout,
    }
    log.info("Parametric sweep for %s: %s", country, summary)
    return summary


# --------------------------------------------------------------------------- #
# Firings (read)
# --------------------------------------------------------------------------- #

_FIRING_COLUMNS = """
    f.id, f.trigger_id, t.name, f.hazard_event_id,
    h.event_type, h.event_id, h.episode_id, h.event_name, h.from_date, h.alert_level,
    f.reason, f.exposed_asset_count, f.exposed_tiv, f.modelled_loss,
    f.payout_amount, f.basis_risk, f.payout_currency, f.evaluated_at
"""


def _row_to_firing(row) -> dict:
    payout = float(row[14])
    modelled = float(row[13])
    return {
        "id": row[0],
        "trigger_id": row[1],
        "trigger_name": row[2],
        "hazard_event_id": row[3],
        "event_type": row[4],
        "event_id": row[5],
        "episode_id": row[6],
        "event_name": row[7],
        "from_date": row[8].isoformat() if row[8] else None,
        "alert_level": row[9],
        "reason": row[10],
        "exposed_asset_count": row[11],
        "exposed_tiv": float(row[12]),
        "modelled_loss": modelled,
        "payout_amount": payout,
        "basis_risk": float(row[15]),
        "basis_risk_pct": (payout - modelled) / modelled if modelled > 0 else None,
        "payout_currency": row[16],
        "evaluated_at": row[17].isoformat() if row[17] else None,
    }


def summary() -> dict:
    """Portfolio-level parametric position, for the dashboard header: how many
    rules exist / are active, and the outstanding payout and net basis risk
    across every firing currently in the ledger."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (SELECT count(*) FROM parametric_triggers),
                    (SELECT count(*) FROM parametric_triggers WHERE is_active),
                    (SELECT count(*) FROM trigger_firings),
                    (SELECT count(DISTINCT hazard_event_id) FROM trigger_firings),
                    (SELECT COALESCE(sum(payout_amount), 0) FROM trigger_firings),
                    (SELECT COALESCE(sum(basis_risk), 0) FROM trigger_firings)
                """
            )
            row = cur.fetchone()
    return {
        "rule_count": row[0],
        "active_rule_count": row[1],
        "firing_count": row[2],
        "events_with_firings": row[3],
        "total_outstanding_payout": float(row[4]),
        "total_basis_risk": float(row[5]),
    }


def list_firings(
    hazard_event_id: Optional[int] = None,
    trigger_id: Optional[int] = None,
) -> list[dict]:
    clauses = []
    params: list = []
    if hazard_event_id is not None:
        clauses.append("f.hazard_event_id = %s")
        params.append(hazard_event_id)
    if trigger_id is not None:
        clauses.append("f.trigger_id = %s")
        params.append(trigger_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_FIRING_COLUMNS}
                FROM trigger_firings f
                JOIN parametric_triggers t ON t.id = f.trigger_id
                JOIN hazard_events h ON h.id = f.hazard_event_id
                {where}
                ORDER BY f.evaluated_at DESC, f.id DESC
                """,
                params,
            )
            return [_row_to_firing(r) for r in cur.fetchall()]
