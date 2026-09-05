from __future__ import annotations

import copy
from dataclasses import replace
from datetime import date

import pytest

from fdre.research import historical_universe_identity_adjudication as adjudication
from fdre.research.historical_universe_identity_adjudication import (
    IdentityAction,
    IdentityAdjudicationCase,
    IdentityAnchor,
    IdentityEvidence,
    MembershipAnchor,
    identity_adjudication_manifest_id,
    identity_adjudication_plan_id,
)
from fdre.research.historical_universe_identity_adjudication_manifest import (
    CORRECTION_SPECS,
    INSERT_SPECS,
    VERIFY_IDENTITY_IDS,
)


def _membership_anchor() -> MembershipAnchor:
    return MembershipAnchor(
        membership_id=1,
        security_id=1,
        cik="0000000001",
        universe_code="sp500",
        effective_from=date(2020, 1, 1),
        effective_to=None,
        verification_status="verified",
        source_hash="m" * 64,
    )


def _case(
    *,
    case_id: str,
    action: IdentityAction = "verify",
    security_id: int = 1,
    symbol: str = "AAA",
) -> IdentityAdjudicationCase:
    prior_from = None if action == "insert" else date(2020, 1, 1)
    prior_to = None if action == "insert" else date(2020, 2, 1)
    target_from = date(2020, 1, 15) if action == "insert" else date(2020, 1, 1)
    target_to = date(2020, 1, 20) if action == "insert" else date(2020, 2, 1)
    if action == "correct_and_verify":
        target_from = date(2019, 12, 31)
    return IdentityAdjudicationCase(
        case_id=case_id,
        action=action,
        security_id=security_id,
        cik=f"{security_id:010d}",
        symbol=symbol,
        existing_identity_id=None if action == "insert" else security_id,
        prior_effective_from=prior_from,
        prior_effective_to=prior_to,
        prior_source_hash=None if action == "insert" else "s" * 64,
        prior_verification_status=None if action == "insert" else "provisional",
        target_effective_from=target_from,
        target_effective_to=target_to,
        evidence=(
            IdentityEvidence(
                authority="issuer",
                source_url="https://example.test/evidence",
                assertion="Exact reviewed evidence.",
            ),
        ),
        membership_anchors=() if action == "insert" else (_membership_anchor(),),
        name="Inserted Company" if action == "insert" else None,
        exchange="NYSE" if action == "insert" else None,
        reason="Reviewed test decision.",
    )


def _synthetic_cases() -> tuple[IdentityAdjudicationCase, ...]:
    return tuple(
        [
            _case(case_id=f"verify-{index}", security_id=index)
            for index in range(1, 38)
        ]
        + [
            _case(
                case_id=f"correct-{index}",
                action="correct_and_verify",
                security_id=100 + index,
            )
            for index in range(1, 6)
        ]
        + [
            _case(case_id=f"insert-{index}", action="insert", security_id=200 + index)
            for index in range(1, 4)
        ]
    )


def _frozen_shape() -> dict[str, object]:
    targets = [
        {
            "identity_id": index,
            "security_id": index,
            "cik": f"{index:010d}",
            "symbol": f"T{index}",
            "effective_from": "2020-01-01",
            "effective_to": None,
            "source_hash": f"{index:064x}",
            "identity_periods": [
                {
                    "identity_id": index,
                    "security_id": index,
                    "symbol": f"T{index}",
                    "effective_from": "2020-01-01",
                    "effective_to": None,
                    "verification_status": "provisional",
                    "source_hash": f"{index:064x}",
                },
                {
                    "identity_id": index + 1000,
                    "security_id": index,
                    "symbol": f"T{index}",
                    "effective_from": "2019-01-01",
                    "effective_to": "2020-01-01",
                    "verification_status": "verified",
                    "source_hash": f"{index + 1000:064x}",
                },
            ],
        }
        for index in range(1, 40)
    ]
    return {
        "schema_version": "fdre-hu5-residual-identity-topology-v1",
        "audit_id": adjudication.EXPECTED_TOPOLOGY_AUDIT_ID,
        "topology_id": "",
        "target_count": 39,
        "gap_count": 4,
        "strict_eligible_day_count": 1426,
        "blocked_day_count": 4662,
        "targets": targets,
        "gaps": [{"membership_id": index} for index in range(1, 5)],
    }


def _bind_synthetic_topology(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    payload = _frozen_shape()
    topology_id = adjudication._hash(
        {
            "schema_version": payload["schema_version"],
            "audit_id": payload["audit_id"],
            "targets": payload["targets"],
            "gaps": payload["gaps"],
        }
    )
    payload["topology_id"] = topology_id
    monkeypatch.setattr(adjudication, "EXPECTED_TOPOLOGY_ID", topology_id)
    adjudication._validate_topology_payload(payload)
    return payload


def test_manifest_has_exact_final_action_inventory() -> None:
    assert len(VERIFY_IDENTITY_IDS) == 37
    assert len(set(VERIFY_IDENTITY_IDS)) == 37
    assert len(CORRECTION_SPECS) == 5
    assert len(INSERT_SPECS) == 3
    assert 37 + 5 + 3 == 45


def test_duplicate_target_ids_are_rejected() -> None:
    with pytest.raises(RuntimeError, match="duplicates"):
        adjudication._target_map(
            {"targets": [{"identity_id": 1}, {"identity_id": 1}]}
        )


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        (("targets", 0, "source_hash"), "0" * 64),
        (("targets", 0, "effective_from"), "2019-12-31"),
        (("targets", 0, "cik"), "9999999999"),
        (("targets", 0, "symbol"), "DRIFT"),
    ],
)
def test_frozen_row_drift_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    mutation: tuple[str, int, str],
    value: str,
) -> None:
    payload = _bind_synthetic_topology(monkeypatch)
    changed = copy.deepcopy(payload)
    rows = changed[mutation[0]]
    assert isinstance(rows, list)
    row = rows[mutation[1]]
    assert isinstance(row, dict)
    row[mutation[2]] = value
    with pytest.raises(RuntimeError, match="frozen topology drifted"):
        adjudication._validate_topology_payload(changed)


def test_missing_sibling_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _bind_synthetic_topology(monkeypatch)
    changed = copy.deepcopy(payload)
    targets = changed["targets"]
    assert isinstance(targets, list)
    first = targets[0]
    assert isinstance(first, dict)
    periods = first["identity_periods"]
    assert isinstance(periods, list)
    periods.pop()
    with pytest.raises(RuntimeError, match="frozen topology drifted"):
        adjudication._validate_topology_payload(changed)


def test_correction_requires_a_boundary_change() -> None:
    case = _case(case_id="correction", action="correct_and_verify")
    prior_from = case.prior_effective_from
    assert prior_from is not None
    unchanged = replace(
        case,
        target_effective_from=prior_from,
        target_effective_to=case.prior_effective_to,
    )
    with pytest.raises(ValueError, match="must change a boundary"):
        adjudication._validate_case_shape(unchanged)


def test_verify_cannot_change_a_boundary() -> None:
    changed = replace(
        _case(case_id="verify"),
        target_effective_from=date(2019, 12, 31),
    )
    with pytest.raises(ValueError, match="cannot change boundaries"):
        adjudication._validate_case_shape(changed)


def test_insert_is_exactly_adjacent_without_overlap() -> None:
    insert = replace(
        _case(case_id="insert", action="insert"),
        identity_anchors=(
            IdentityAnchor(
                identity_id=10,
                security_id=1,
                cik="0000000001",
                symbol="OLD",
                effective_from=date(2020, 1, 1),
                effective_to=date(2020, 1, 15),
                verification_status="verified",
                source_hash="a" * 64,
            ),
            IdentityAnchor(
                identity_id=11,
                security_id=1,
                cik="0000000001",
                symbol="NEW",
                effective_from=date(2020, 1, 20),
                effective_to=None,
                verification_status="verified",
                source_hash="b" * 64,
            ),
        ),
    )
    adjudication._validate_final_identity_intervals((insert,))

    overlapping = replace(
        insert,
        identity_anchors=(replace(insert.identity_anchors[0], effective_to=date(2020, 1, 16)),),
    )
    with pytest.raises(RuntimeError, match="reviewed identities overlap"):
        adjudication._validate_final_identity_intervals((overlapping,))


def test_final_transition_boundaries_are_exact() -> None:
    corrections = {item.identity_id: item for item in CORRECTION_SPECS}
    inserts = {item.symbol: item for item in INSERT_SPECS}
    assert corrections[399].target_to == date(2026, 6, 24)
    assert corrections[1164].target_from == date(2021, 10, 4)
    assert corrections[1170].target_from == date(2011, 5, 20)
    assert corrections[1325].target_from == date(2011, 6, 2)
    assert corrections[1401].target_to == date(2014, 3, 24)
    assert (inserts["ECHO"].target_from, inserts["ECHO"].target_to) == (
        date(2026, 6, 24),
        None,
    )
    assert (inserts["COG"].target_from, inserts["COG"].target_to) == (
        date(2021, 10, 3),
        date(2021, 10, 4),
    )
    assert (inserts["SPGI"].target_from, inserts["SPGI"].target_to) == (
        date(2016, 4, 28),
        date(2016, 5, 3),
    )


def test_manifest_and_plan_ids_are_deterministic() -> None:
    cases = _synthetic_cases()
    first_manifest = identity_adjudication_manifest_id(cases)
    second_manifest = identity_adjudication_manifest_id(tuple(reversed(cases)))
    assert first_manifest == second_manifest
    assert identity_adjudication_plan_id(cases, manifest_id=first_manifest) == (
        identity_adjudication_plan_id(
            tuple(reversed(cases)),
            manifest_id=second_manifest,
        )
    )
