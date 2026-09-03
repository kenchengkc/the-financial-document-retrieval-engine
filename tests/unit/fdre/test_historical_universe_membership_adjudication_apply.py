from __future__ import annotations

from fdre.research.historical_universe_membership_adjudication import (
    MEMBERSHIP_ADJUDICATION_SCHEMA_VERSION,
    MembershipAdjudicationCase,
    MembershipAdjudicationDecision,
    membership_adjudication_manifest_id,
    membership_adjudication_plan_id,
)
from fdre.research.historical_universe_membership_adjudication_apply import (
    applied_membership_adjudication_source_hash,
    validate_membership_adjudication_projection,
)
from fdre.research.historical_universe_membership_adjudication_manifest import (
    HU5_MEMBERSHIP_ADJUDICATION_CASES,
)


def _decision(case: MembershipAdjudicationCase) -> MembershipAdjudicationDecision:
    return MembershipAdjudicationDecision(
        membership_id=case.membership_id,
        security_id=case.security_id,
        cik=case.cik,
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


def _payload() -> dict[str, object]:
    decisions = tuple(_decision(case) for case in HU5_MEMBERSHIP_ADJUDICATION_CASES)
    manifest_id = membership_adjudication_manifest_id(HU5_MEMBERSHIP_ADJUDICATION_CASES)
    return {
        "schema_version": MEMBERSHIP_ADJUDICATION_SCHEMA_VERSION,
        "mode": "projection",
        "manifest_id": manifest_id,
        "plan_id": membership_adjudication_plan_id(decisions, manifest_id=manifest_id),
        "decisions": [item.as_dict() for item in decisions],
    }


def test_validate_projection_reproduces_reviewed_manifest() -> None:
    payload = _payload()
    validated = validate_membership_adjudication_projection(
        payload,
        expected_plan_id=str(payload["plan_id"]),
        cases=HU5_MEMBERSHIP_ADJUDICATION_CASES,
    )
    assert len(validated) == 15
    assert {item.membership_id for item in validated} == {
        item.membership_id for item in HU5_MEMBERSHIP_ADJUDICATION_CASES
    }


def test_validate_projection_rejects_decision_tampering() -> None:
    payload = _payload()
    decisions = payload["decisions"]
    assert isinstance(decisions, list)
    first = decisions[0]
    assert isinstance(first, dict)
    first["target_effective_from"] = "1999-01-01"
    try:
        validate_membership_adjudication_projection(
            payload,
            expected_plan_id=str(payload["plan_id"]),
            cases=HU5_MEMBERSHIP_ADJUDICATION_CASES,
        )
    except RuntimeError as exc:
        assert "decision payload changed" in str(exc)
    else:
        raise AssertionError("tampered projection should fail closed")


def test_validate_projection_rejects_manifest_drift() -> None:
    payload = _payload()
    payload["manifest_id"] = "0" * 64
    try:
        validate_membership_adjudication_projection(
            payload,
            expected_plan_id=str(payload["plan_id"]),
            cases=HU5_MEMBERSHIP_ADJUDICATION_CASES,
        )
    except RuntimeError as exc:
        assert "manifest ID mismatch" in str(exc)
    else:
        raise AssertionError("changed manifest ID should fail closed")


def test_applied_source_hash_binds_plan_manifest_and_target_bounds() -> None:
    decision = _decision(HU5_MEMBERSHIP_ADJUDICATION_CASES[0])
    first = applied_membership_adjudication_source_hash(
        decision,
        plan_id="1" * 64,
        manifest_id="2" * 64,
    )
    second = applied_membership_adjudication_source_hash(
        decision,
        plan_id="3" * 64,
        manifest_id="2" * 64,
    )
    third = applied_membership_adjudication_source_hash(
        decision,
        plan_id="1" * 64,
        manifest_id="4" * 64,
    )
    assert len(first) == 64
    assert first != second
    assert first != third
