"""Validation and provenance helpers for applying final HU-5 membership adjudications."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, cast

from fdre.research.historical_universe_membership_adjudication import (
    MEMBERSHIP_ADJUDICATION_SCHEMA_VERSION,
    AdjudicationAction,
    MembershipAdjudicationCase,
    MembershipAdjudicationDecision,
    membership_adjudication_manifest_id,
    membership_adjudication_plan_id,
)

MEMBERSHIP_ADJUDICATION_APPLY_SCHEMA_VERSION = "fdre-hu5-membership-adjudication-apply-v1"


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_str(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{field} must be a non-empty string")
    return value


def _optional_date(value: Any, *, field: str) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(_required_str(value, field=field))


def _required_int_list(value: Any, *, field: str) -> tuple[int, ...]:
    if not isinstance(value, list) or not all(isinstance(item, int) for item in value):
        raise RuntimeError(f"{field} must be an integer list")
    normalized = tuple(cast(list[int], value))
    if tuple(sorted(set(normalized))) != normalized:
        raise RuntimeError(f"{field} must be sorted and unique")
    return normalized


def _required_str_list(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError(f"{field} must be a string list")
    normalized = tuple(cast(list[str], value))
    if tuple(sorted(set(normalized))) != normalized:
        raise RuntimeError(f"{field} must be sorted and unique")
    return normalized


def _decision_from_payload(
    raw: Any,
    *,
    cases_by_id: dict[int, MembershipAdjudicationCase],
) -> MembershipAdjudicationDecision:
    if not isinstance(raw, dict):
        raise RuntimeError("membership adjudication decision must be an object")
    try:
        membership_id = int(raw["membership_id"])
        security_id = int(raw["security_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("membership_id and security_id must be integers") from exc
    case = cases_by_id.get(membership_id)
    if case is None:
        raise RuntimeError(f"membership {membership_id} is not in the reviewed manifest")
    action_raw = _required_str(raw.get("action"), field="action")
    if action_raw not in {"verify", "correct_and_verify", "reject"}:
        raise RuntimeError(f"unsupported adjudication action: {action_raw}")
    action = cast(AdjudicationAction, action_raw)
    decision = MembershipAdjudicationDecision(
        membership_id=membership_id,
        security_id=security_id,
        cik=_required_str(raw.get("cik"), field="cik"),
        prior_effective_from=date.fromisoformat(
            _required_str(raw.get("prior_effective_from"), field="prior_effective_from")
        ),
        prior_effective_to=_optional_date(
            raw.get("prior_effective_to"), field="prior_effective_to"
        ),
        prior_source_hash=_required_str(
            raw.get("prior_source_hash"), field="prior_source_hash"
        ),
        action=action,
        target_effective_from=date.fromisoformat(
            _required_str(raw.get("target_effective_from"), field="target_effective_from")
        ),
        target_effective_to=_optional_date(
            raw.get("target_effective_to"), field="target_effective_to"
        ),
        evidence_ids=_required_str_list(raw.get("evidence_ids"), field="evidence_ids"),
        sibling_membership_ids=_required_int_list(
            raw.get("sibling_membership_ids"), field="sibling_membership_ids"
        ),
        reason=_required_str(raw.get("reason"), field="reason"),
        decision_hash=_required_str(raw.get("decision_hash"), field="decision_hash"),
    )
    expected = MembershipAdjudicationDecision(
        membership_id=case.membership_id,
        security_id=case.security_id,
        cik=case.cik.zfill(10) if case.cik.isdigit() else case.cik,
        prior_effective_from=case.prior_effective_from,
        prior_effective_to=case.prior_effective_to,
        prior_source_hash=case.prior_source_hash,
        action=case.action,
        target_effective_from=case.target_effective_from,
        target_effective_to=case.target_effective_to,
        evidence_ids=tuple(sorted(item.evidence_id for item in case.evidence)),
        sibling_membership_ids=tuple(sorted(item.membership_id for item in case.siblings)),
        reason=case.reason,
        decision_hash=case.decision_hash,
    )
    if decision != expected:
        raise RuntimeError(f"decision payload changed for membership {membership_id}")
    return decision


def validate_membership_adjudication_projection(
    payload: Any,
    *,
    expected_plan_id: str,
    cases: tuple[MembershipAdjudicationCase, ...],
) -> tuple[MembershipAdjudicationDecision, ...]:
    if not isinstance(payload, dict):
        raise RuntimeError("membership adjudication projection root must be an object")
    if payload.get("schema_version") != MEMBERSHIP_ADJUDICATION_SCHEMA_VERSION:
        raise RuntimeError("unexpected membership adjudication schema version")
    if payload.get("mode") != "projection":
        raise RuntimeError("membership adjudication apply requires a projection payload")
    manifest_id = membership_adjudication_manifest_id(cases)
    if payload.get("manifest_id") != manifest_id:
        raise RuntimeError("membership adjudication manifest ID mismatch")
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, list):
        raise RuntimeError("projection decisions must be a list")
    cases_by_id = {item.membership_id: item for item in cases}
    if len(cases_by_id) != len(cases):
        raise RuntimeError("reviewed membership manifest contains duplicate IDs")
    decisions = tuple(
        _decision_from_payload(item, cases_by_id=cases_by_id) for item in raw_decisions
    )
    if {item.membership_id for item in decisions} != set(cases_by_id):
        raise RuntimeError("projection decision set differs from reviewed manifest")
    computed_plan = membership_adjudication_plan_id(decisions, manifest_id=manifest_id)
    if payload.get("plan_id") != computed_plan or expected_plan_id != computed_plan:
        raise RuntimeError("membership adjudication plan ID mismatch")
    return decisions


def applied_membership_adjudication_source_hash(
    decision: MembershipAdjudicationDecision,
    *,
    plan_id: str,
    manifest_id: str,
) -> str:
    return _hash(
        {
            "schema_version": MEMBERSHIP_ADJUDICATION_APPLY_SCHEMA_VERSION,
            "manifest_id": manifest_id,
            "plan_id": plan_id,
            "decision_hash": decision.decision_hash,
            "membership_id": decision.membership_id,
            "prior_source_hash": decision.prior_source_hash,
            "action": decision.action,
            "target_effective_from": decision.target_effective_from.isoformat(),
            "target_effective_to": (
                decision.target_effective_to.isoformat()
                if decision.target_effective_to
                else None
            ),
            "evidence_ids": list(decision.evidence_ids),
            "sibling_membership_ids": list(decision.sibling_membership_ids),
        }
    )
