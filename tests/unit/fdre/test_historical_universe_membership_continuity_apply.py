from __future__ import annotations

from datetime import date
import hashlib
import json
from typing import cast

import pytest

from fdre.research.historical_universe_membership_continuity import (
    ContinuityAction,
    ContinuityMethod,
    MembershipContinuityDecision,
    membership_continuity_plan_id,
)
from fdre.research.historical_universe_membership_continuity_apply import (
    applied_membership_source_hash,
    validate_membership_continuity_projection,
)


REF = "c" * 40


def _decision(*, action: str = "verify") -> MembershipContinuityDecision:
    method = {
        "verify": "current_constituent_anchor",
        "reject": "single_verified_sibling_cover",
        "unresolved": "unresolved",
    }[action]
    evidence_ids = () if action == "unresolved" else ("e" * 64,)
    reason = "fixture decision"
    base = MembershipContinuityDecision(
        membership_id=12,
        security_id=34,
        cik="0000000123",
        effective_from=date(2020, 1, 2),
        effective_to=None,
        prior_source_hash="a" * 64,
        action=cast(ContinuityAction, action),
        method=cast(ContinuityMethod, method),
        evidence_ids=evidence_ids,
        reason=reason,
        decision_hash="",
    )
    payload = {
        "schema_version": "fdre-hu5-membership-continuity-v1",
        "membership_id": base.membership_id,
        "security_id": base.security_id,
        "cik": base.cik,
        "effective_from": base.effective_from.isoformat(),
        "effective_to": None,
        "prior_source_hash": base.prior_source_hash,
        "action": base.action,
        "method": base.method,
        "evidence_ids": list(base.evidence_ids),
        "reason": base.reason,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return MembershipContinuityDecision(
        membership_id=base.membership_id,
        security_id=base.security_id,
        cik=base.cik,
        effective_from=base.effective_from,
        effective_to=base.effective_to,
        prior_source_hash=base.prior_source_hash,
        action=base.action,
        method=base.method,
        evidence_ids=base.evidence_ids,
        reason=base.reason,
        decision_hash=digest,
    )


def _payload(decision: MembershipContinuityDecision) -> dict[str, object]:
    decisions = (decision,)
    return {
        "schema_version": "fdre-hu5-membership-continuity-v1",
        "mode": "projection",
        "current_constituents_ref": REF,
        "plan_id": membership_continuity_plan_id(decisions, current_source_ref=REF),
        "decisions": [decision.as_dict()],
    }


def test_validate_projection_recomputes_plan_and_decision_hashes() -> None:
    decision = _decision()
    payload = _payload(decision)
    validated = validate_membership_continuity_projection(
        payload,
        expected_plan_id=str(payload["plan_id"]),
        expected_current_source_ref=REF,
    )
    assert validated == (decision,)


def test_validate_projection_rejects_decision_tampering() -> None:
    decision = _decision()
    payload = _payload(decision)
    raw_decisions = payload["decisions"]
    assert isinstance(raw_decisions, list)
    raw = raw_decisions[0]
    assert isinstance(raw, dict)
    raw["membership_id"] = 99
    with pytest.raises(RuntimeError, match="decision hash mismatch"):
        validate_membership_continuity_projection(
            payload,
            expected_plan_id=str(payload["plan_id"]),
            expected_current_source_ref=REF,
        )


def test_validate_projection_rejects_action_method_mismatch() -> None:
    decision = _decision(action="reject")
    payload = _payload(decision)
    raw_decisions = payload["decisions"]
    assert isinstance(raw_decisions, list)
    raw = raw_decisions[0]
    assert isinstance(raw, dict)
    raw["method"] = "current_constituent_anchor"
    with pytest.raises(RuntimeError, match="invalid method"):
        validate_membership_continuity_projection(
            payload,
            expected_plan_id=str(payload["plan_id"]),
            expected_current_source_ref=REF,
        )


def test_applied_source_hash_binds_plan_and_decision() -> None:
    decision = _decision()
    first = applied_membership_source_hash(decision, plan_id="1" * 64)
    second = applied_membership_source_hash(decision, plan_id="2" * 64)
    assert first != second
    assert len(first) == 64
