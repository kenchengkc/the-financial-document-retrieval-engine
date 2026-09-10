"""Provenance helpers shared by final HU-5 identity projection and production apply."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from fdre.research.historical_universe_identity_adjudication import (
    EXPECTED_ACTION_COUNTS,
    EXPECTED_RESIDUAL_SEC_PLAN_ID,
    EXPECTED_TOPOLOGY_AUDIT_ID,
    EXPECTED_TOPOLOGY_ID,
    IdentityAdjudicationCase,
    identity_adjudication_manifest_id,
    identity_adjudication_plan_id,
)

IDENTITY_ADJUDICATION_APPLY_SCHEMA_VERSION = "fdre-hu5-final-identity-adjudication-apply-v1"
IDENTITY_ADJUDICATION_PROJECTION_SCHEMA_VERSION = (
    "fdre-hu5-final-identity-adjudication-projection-v1"
)
REVIEWED_SOURCE_OBSERVED_AT = datetime(2026, 9, 4, 6, 40, tzinfo=UTC)
APPLIED_SOURCE_SUFFIX = "hu5-final-identity-adjudication"


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def applied_identity_source_hash(
    case: IdentityAdjudicationCase,
    *,
    manifest_id: str,
    plan_id: str,
) -> str:
    return _hash(
        {
            "schema_version": IDENTITY_ADJUDICATION_APPLY_SCHEMA_VERSION,
            "manifest_id": manifest_id,
            "plan_id": plan_id,
            "case_id": case.case_id,
            "decision_hash": case.decision_hash,
            "action": case.action,
            "security_id": case.security_id,
            "cik": case.cik,
            "symbol": case.symbol,
            "prior_source_hash": case.prior_source_hash,
            "target_effective_from": case.target_effective_from.isoformat(),
            "target_effective_to": (
                case.target_effective_to.isoformat() if case.target_effective_to else None
            ),
            "evidence_ids": sorted(item.evidence_id for item in case.evidence),
        }
    )


def _strict_metrics(payload: Any, *, field: str) -> dict[str, int]:
    if not isinstance(payload, dict):
        raise RuntimeError(f"{field} must be an object")
    expected = {
        "day_count": 6088,
        "strict_eligible_day_count": 6088,
    }
    actual = {key: payload.get(key) for key in expected}
    if actual != expected:
        raise RuntimeError(f"{field} strict coverage differs: {actual}")
    return expected


def validate_identity_adjudication_projection(
    payload: Any,
    *,
    expected_plan_id: str,
    cases: tuple[IdentityAdjudicationCase, ...],
) -> tuple[IdentityAdjudicationCase, ...]:
    """Replay an exact projection artifact against the reviewed case inventory."""

    if not isinstance(payload, dict):
        raise RuntimeError("identity adjudication projection root must be an object")
    expected_header = {
        "schema_version": IDENTITY_ADJUDICATION_PROJECTION_SCHEMA_VERSION,
        "mode": "projection",
        "applied": False,
        "transaction_rolled_back": True,
        "frozen_audit_id": EXPECTED_TOPOLOGY_AUDIT_ID,
        "frozen_topology_id": EXPECTED_TOPOLOGY_ID,
        "frozen_residual_sec_plan_id": EXPECTED_RESIDUAL_SEC_PLAN_ID,
    }
    actual_header = {key: payload.get(key) for key in expected_header}
    if actual_header != expected_header:
        raise RuntimeError(f"identity projection header differs: {actual_header}")

    ordered = tuple(sorted(cases, key=lambda item: item.case_id))
    manifest_id = identity_adjudication_manifest_id(ordered)
    if payload.get("manifest_id") != manifest_id:
        raise RuntimeError("identity adjudication manifest ID mismatch")
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, list):
        raise RuntimeError("identity projection decisions must be a list")
    expected_decisions = [
        {**case.as_dict(), "decision_hash": case.decision_hash} for case in ordered
    ]
    if raw_decisions != expected_decisions:
        raise RuntimeError("identity projection decisions differ from reviewed manifest")

    counts = Counter(item.action for item in ordered)
    expected_counts = {
        action: counts[action]
        for action in ("verify", "correct_and_verify", "insert")
    }
    if expected_counts != EXPECTED_ACTION_COUNTS:
        raise RuntimeError(f"reviewed action counts differ: {expected_counts}")
    if payload.get("action_count") != len(ordered):
        raise RuntimeError("identity projection action count differs")
    if payload.get("action_counts") != expected_counts:
        raise RuntimeError("identity projection category counts differ")

    computed_plan_id = identity_adjudication_plan_id(
        ordered,
        manifest_id=manifest_id,
    )
    if payload.get("plan_id") != computed_plan_id or expected_plan_id != computed_plan_id:
        raise RuntimeError("identity adjudication plan ID mismatch")

    gate = payload.get("strict_coverage_projected")
    _strict_metrics(gate, field="strict_coverage_projected")
    if not isinstance(gate, dict) or gate.get("invalid_day_count") != 0:
        raise RuntimeError("projected merged gate contains invalid days")
    audit = payload.get("identity_strict_coverage_projected")
    _strict_metrics(audit, field="identity_strict_coverage_projected")
    if not isinstance(audit, dict):
        raise RuntimeError("identity_strict_coverage_projected must be an object")
    if (
        audit.get("blocked_day_count") != 0
        or audit.get("relevant_provisional_identity_count") != 0
    ):
        raise RuntimeError("projected identity-strict audit retains blockers")
    expected_audit = {
        "blocked_day_count": 0,
        "relevant_provisional_identity_count": 0,
        "relevant_provisional_identity_ids": [],
    }
    actual_audit = {key: audit.get(key) for key in expected_audit}
    if actual_audit != expected_audit:
        raise RuntimeError(f"projected identity audit differs: {actual_audit}")
    return ordered
