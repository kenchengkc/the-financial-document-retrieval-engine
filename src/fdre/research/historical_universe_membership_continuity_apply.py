"""Validation and provenance helpers for HU-5 membership continuity applies."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from fdre.research.historical_universe_membership_continuity import (
    MEMBERSHIP_CONTINUITY_SCHEMA_VERSION,
    MembershipContinuityDecision,
    membership_continuity_plan_id,
)

MEMBERSHIP_CONTINUITY_APPLY_SCHEMA_VERSION = "fdre-hu5-membership-continuity-apply-v1"


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _optional_date(value: Any, *, field: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"{field} must be an ISO date or null")
    return date.fromisoformat(value)


def _required_str(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{field} must be a non-empty string")
    return value


def _decision_from_payload(raw: Any) -> MembershipContinuityDecision:
    if not isinstance(raw, dict):
        raise RuntimeError("membership continuity decision must be an object")
    action = _required_str(raw.get("action"), field="action")
    method = _required_str(raw.get("method"), field="method")
    if action not in {"verify", "reject", "unresolved"}:
        raise RuntimeError(f"unsupported continuity action: {action}")
    expected_method = {
        "verify": "current_constituent_anchor",
        "reject": "single_verified_sibling_cover",
        "unresolved": "unresolved",
    }[action]
    if method != expected_method:
        raise RuntimeError(f"continuity action {action} has invalid method {method}")
    evidence_raw = raw.get("evidence_ids")
    if not isinstance(evidence_raw, list) or not all(isinstance(item, str) for item in evidence_raw):
        raise RuntimeError("evidence_ids must be a string list")
    evidence_ids = tuple(evidence_raw)
    if tuple(sorted(set(evidence_ids))) != evidence_ids:
        raise RuntimeError("evidence_ids must be sorted and unique")
    if action == "unresolved" and evidence_ids:
        raise RuntimeError("unresolved decisions cannot carry evidence IDs")
    if action != "unresolved" and len(evidence_ids) != 1:
        raise RuntimeError("actionable continuity decisions require exactly one evidence ID")

    try:
        membership_id = int(raw["membership_id"])
        security_id = int(raw["security_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("membership_id and security_id must be integers") from exc
    if membership_id <= 0 or security_id <= 0:
        raise RuntimeError("membership_id and security_id must be positive")
    effective_from = date.fromisoformat(
        _required_str(raw.get("effective_from"), field="effective_from")
    )
    effective_to = _optional_date(raw.get("effective_to"), field="effective_to")
    prior_source_hash = _required_str(raw.get("prior_source_hash"), field="prior_source_hash")
    if len(prior_source_hash) != 64:
        raise RuntimeError("prior_source_hash must be SHA-256")
    reason = _required_str(raw.get("reason"), field="reason")
    decision = MembershipContinuityDecision(
        membership_id=membership_id,
        security_id=security_id,
        cik=_required_str(raw.get("cik"), field="cik"),
        effective_from=effective_from,
        effective_to=effective_to,
        prior_source_hash=prior_source_hash,
        action=action,  # type: ignore[arg-type]
        method=method,  # type: ignore[arg-type]
        evidence_ids=evidence_ids,
        reason=reason,
        decision_hash="",
    )
    canonical = {
        "schema_version": MEMBERSHIP_CONTINUITY_SCHEMA_VERSION,
        "membership_id": decision.membership_id,
        "security_id": decision.security_id,
        "cik": decision.cik,
        "effective_from": decision.effective_from.isoformat(),
        "effective_to": decision.effective_to.isoformat() if decision.effective_to else None,
        "prior_source_hash": decision.prior_source_hash,
        "action": decision.action,
        "method": decision.method,
        "evidence_ids": list(decision.evidence_ids),
        "reason": decision.reason,
    }
    computed_hash = _hash(canonical)
    if raw.get("decision_hash") != computed_hash:
        raise RuntimeError(f"decision hash mismatch for membership {membership_id}")
    return MembershipContinuityDecision(
        membership_id=decision.membership_id,
        security_id=decision.security_id,
        cik=decision.cik,
        effective_from=decision.effective_from,
        effective_to=decision.effective_to,
        prior_source_hash=decision.prior_source_hash,
        action=decision.action,
        method=decision.method,
        evidence_ids=decision.evidence_ids,
        reason=decision.reason,
        decision_hash=computed_hash,
    )


def validate_membership_continuity_projection(
    payload: Any,
    *,
    expected_plan_id: str,
    expected_current_source_ref: str,
) -> tuple[MembershipContinuityDecision, ...]:
    if not isinstance(payload, dict):
        raise RuntimeError("membership continuity projection root must be an object")
    if payload.get("schema_version") != MEMBERSHIP_CONTINUITY_SCHEMA_VERSION:
        raise RuntimeError("unexpected membership continuity schema version")
    if payload.get("mode") != "projection":
        raise RuntimeError("membership continuity apply requires a projection payload")
    if payload.get("current_constituents_ref") != expected_current_source_ref:
        raise RuntimeError("current constituent source ref changed")
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, list):
        raise RuntimeError("projection decisions must be a list")
    decisions = tuple(_decision_from_payload(item) for item in raw_decisions)
    ids = [item.membership_id for item in decisions]
    if len(set(ids)) != len(ids):
        raise RuntimeError("projection contains duplicate membership decisions")
    computed_plan = membership_continuity_plan_id(
        decisions,
        current_source_ref=expected_current_source_ref,
    )
    if payload.get("plan_id") != computed_plan or expected_plan_id != computed_plan:
        raise RuntimeError("membership continuity plan ID mismatch")
    return decisions


def applied_membership_source_hash(
    decision: MembershipContinuityDecision,
    *,
    plan_id: str,
) -> str:
    return _hash(
        {
            "schema_version": MEMBERSHIP_CONTINUITY_APPLY_SCHEMA_VERSION,
            "plan_id": plan_id,
            "decision_hash": decision.decision_hash,
            "membership_id": decision.membership_id,
            "prior_source_hash": decision.prior_source_hash,
            "action": decision.action,
            "method": decision.method,
            "evidence_ids": list(decision.evidence_ids),
        }
    )
