from __future__ import annotations

from collections import Counter
from datetime import date
from typing import cast

import pytest

from fdre.research.historical_universe_identity_adjudication import (
    EXPECTED_RESIDUAL_SEC_PLAN_ID,
    EXPECTED_TOPOLOGY_AUDIT_ID,
    EXPECTED_TOPOLOGY_ID,
    IdentityAction,
    IdentityAdjudicationCase,
    identity_adjudication_manifest_id,
    identity_adjudication_plan_id,
)
from fdre.research.historical_universe_identity_adjudication_apply import (
    IDENTITY_ADJUDICATION_PROJECTION_SCHEMA_VERSION,
    validate_identity_adjudication_projection,
)


def _synthetic_cases() -> tuple[IdentityAdjudicationCase, ...]:
    actions = (("verify", 37), ("correct_and_verify", 5), ("insert", 3))
    security_id = 0
    cases: list[IdentityAdjudicationCase] = []
    for action, count in actions:
        for index in range(1, count + 1):
            security_id += 1
            cases.append(
                IdentityAdjudicationCase(
                    case_id=f"{action}-{index}",
                    action=cast(IdentityAction, action),
                    security_id=security_id,
                    cik=f"{security_id:010d}",
                    symbol=f"T{security_id}",
                    target_effective_from=date(2020, 1, 1),
                    target_effective_to=date(2020, 2, 1),
                    reason="Reviewed synthetic decision.",
                )
            )
    return tuple(cases)


def _payload() -> tuple[dict[str, object], str]:
    cases = tuple(sorted(_synthetic_cases(), key=lambda item: item.case_id))
    manifest_id = identity_adjudication_manifest_id(cases)
    plan_id = identity_adjudication_plan_id(cases, manifest_id=manifest_id)
    counts = Counter(item.action for item in cases)
    payload: dict[str, object] = {
        "schema_version": IDENTITY_ADJUDICATION_PROJECTION_SCHEMA_VERSION,
        "mode": "projection",
        "applied": False,
        "transaction_rolled_back": True,
        "frozen_audit_id": EXPECTED_TOPOLOGY_AUDIT_ID,
        "frozen_topology_id": EXPECTED_TOPOLOGY_ID,
        "frozen_residual_sec_plan_id": EXPECTED_RESIDUAL_SEC_PLAN_ID,
        "manifest_id": manifest_id,
        "plan_id": plan_id,
        "action_count": 45,
        "action_counts": {
            action: counts[action]
            for action in ("verify", "correct_and_verify", "insert")
        },
        "decisions": [
            {**case.as_dict(), "decision_hash": case.decision_hash} for case in cases
        ],
        "strict_coverage_projected": {
            "day_count": 6088,
            "strict_eligible_day_count": 6088,
            "invalid_day_count": 0,
        },
        "identity_strict_coverage_projected": {
            "day_count": 6088,
            "strict_eligible_day_count": 6088,
            "blocked_day_count": 0,
            "relevant_provisional_identity_count": 0,
            "relevant_provisional_identity_ids": [],
        },
    }
    return payload, plan_id


def test_projection_validator_replays_all_decisions() -> None:
    payload, plan_id = _payload()
    cases = _synthetic_cases()
    validated = validate_identity_adjudication_projection(
        payload,
        expected_plan_id=plan_id,
        cases=cases,
    )
    assert len(validated) == 45


def test_projection_validator_rejects_modified_decision() -> None:
    payload, plan_id = _payload()
    decisions = payload["decisions"]
    assert isinstance(decisions, list)
    first = decisions[0]
    assert isinstance(first, dict)
    first["reason"] = "tampered"
    with pytest.raises(RuntimeError, match="decisions differ"):
        validate_identity_adjudication_projection(
            payload,
            expected_plan_id=plan_id,
            cases=_synthetic_cases(),
        )


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("strict_coverage_projected", "invalid_day_count", 1),
        ("identity_strict_coverage_projected", "blocked_day_count", 1),
        (
            "identity_strict_coverage_projected",
            "relevant_provisional_identity_count",
            1,
        ),
    ],
)
def test_projection_validator_requires_exact_closure(
    section: str,
    field: str,
    value: int,
) -> None:
    payload, plan_id = _payload()
    metrics = payload[section]
    assert isinstance(metrics, dict)
    metrics[field] = value
    with pytest.raises(RuntimeError):
        validate_identity_adjudication_projection(
            payload,
            expected_plan_id=plan_id,
            cases=_synthetic_cases(),
        )
