from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from fdre.research.historical_universe_membership_adjudication import (
    LiveSiblingMembership,
    MembershipAdjudicationCase,
    membership_adjudication_manifest_id,
    membership_adjudication_plan_id,
    plan_membership_adjudication,
)
from fdre.research.historical_universe_membership_adjudication_manifest import (
    HU5_MEMBERSHIP_ADJUDICATION_CASES,
)
from fdre.research.historical_universe_strict_coverage import (
    IdentityContext,
    ProvisionalMembershipBlocker,
)


def _blocker(case_index: int) -> ProvisionalMembershipBlocker:
    case = HU5_MEMBERSHIP_ADJUDICATION_CASES[case_index]
    identity = case.identity
    return ProvisionalMembershipBlocker(
        membership_id=case.membership_id,
        security_id=case.security_id,
        cik=case.cik,
        effective_from=case.prior_effective_from,
        effective_to=case.prior_effective_to,
        source="lawcal",
        source_url=None,
        source_hash=case.prior_source_hash,
        confidence=0.85,
        identities=(
            IdentityContext(
                symbol=identity.symbol,
                effective_from=identity.effective_from,
                effective_to=identity.effective_to,
                verification_status=identity.verification_status,
                source_hash=identity.source_hash,
            ),
        ),
    )


def _blockers() -> tuple[ProvisionalMembershipBlocker, ...]:
    return tuple(
        _blocker(index) for index in range(len(HU5_MEMBERSHIP_ADJUDICATION_CASES))
    )


def _siblings(*, status: str = "verified") -> tuple[LiveSiblingMembership, ...]:
    requirements = {
        sibling.membership_id: sibling
        for case in HU5_MEMBERSHIP_ADJUDICATION_CASES
        for sibling in case.siblings
    }
    return tuple(
        LiveSiblingMembership(
            membership_id=item.membership_id,
            security_id=item.security_id,
            cik=item.cik,
            effective_from=item.effective_from,
            effective_to=item.effective_to,
            source_hash=item.source_hash,
            verification_status=status,
        )
        for item in sorted(requirements.values(), key=lambda value: value.membership_id)
    )


def _case(membership_id: int) -> MembershipAdjudicationCase:
    return next(
        item
        for item in HU5_MEMBERSHIP_ADJUDICATION_CASES
        if item.membership_id == membership_id
    )


def _replace_case(
    replacement: MembershipAdjudicationCase,
) -> tuple[MembershipAdjudicationCase, ...]:
    return tuple(
        replacement if item.membership_id == replacement.membership_id else item
        for item in HU5_MEMBERSHIP_ADJUDICATION_CASES
    )


def test_manifest_covers_exact_final_membership_inventory() -> None:
    ids = [item.membership_id for item in HU5_MEMBERSHIP_ADJUDICATION_CASES]
    assert len(ids) == 15
    assert len(set(ids)) == 15
    assert sum(item.action == "verify" for item in HU5_MEMBERSHIP_ADJUDICATION_CASES) == 6
    assert sum(
        item.action == "correct_and_verify"
        for item in HU5_MEMBERSHIP_ADJUDICATION_CASES
    ) == 6
    assert sum(item.action == "reject" for item in HU5_MEMBERSHIP_ADJUDICATION_CASES) == 3


def test_full_manifest_plans_deterministically() -> None:
    manifest_id = membership_adjudication_manifest_id(HU5_MEMBERSHIP_ADJUDICATION_CASES)
    first = plan_membership_adjudication(
        _blockers(),
        cases=HU5_MEMBERSHIP_ADJUDICATION_CASES,
        live_siblings=_siblings(),
    )
    second = plan_membership_adjudication(
        tuple(reversed(_blockers())),
        cases=tuple(reversed(HU5_MEMBERSHIP_ADJUDICATION_CASES)),
        live_siblings=tuple(reversed(_siblings())),
    )
    assert first == second
    assert membership_adjudication_plan_id(first, manifest_id=manifest_id) == (
        membership_adjudication_plan_id(second, manifest_id=manifest_id)
    )


def test_blocker_set_drift_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="live provisional membership set differs"):
        plan_membership_adjudication(
            _blockers()[:-1],
            cases=HU5_MEMBERSHIP_ADJUDICATION_CASES,
            live_siblings=_siblings(),
        )


def test_source_hash_drift_fails_closed() -> None:
    blockers = list(_blockers())
    blockers[0] = replace(blockers[0], source_hash="0" * 64)
    with pytest.raises(RuntimeError, match="source hash changed"):
        plan_membership_adjudication(
            blockers,
            cases=HU5_MEMBERSHIP_ADJUDICATION_CASES,
            live_siblings=_siblings(),
        )


def test_identity_drift_fails_closed() -> None:
    blockers = list(_blockers())
    identity = blockers[0].identities[0]
    blockers[0] = replace(
        blockers[0],
        identities=(replace(identity, symbol="DRIFT"),),
    )
    with pytest.raises(RuntimeError, match="identity anchor changed"):
        plan_membership_adjudication(
            blockers,
            cases=HU5_MEMBERSHIP_ADJUDICATION_CASES,
            live_siblings=_siblings(),
        )


def test_required_sibling_must_remain_verified() -> None:
    with pytest.raises(RuntimeError, match="is not verified"):
        plan_membership_adjudication(
            _blockers(),
            cases=HU5_MEMBERSHIP_ADJUDICATION_CASES,
            live_siblings=_siblings(status="provisional"),
        )


def test_required_sibling_source_hash_is_bound() -> None:
    siblings = list(_siblings())
    siblings[0] = replace(siblings[0], source_hash="0" * 64)
    with pytest.raises(RuntimeError, match="required sibling membership .* changed"):
        plan_membership_adjudication(
            _blockers(),
            cases=HU5_MEMBERSHIP_ADJUDICATION_CASES,
            live_siblings=siblings,
        )


def test_verify_action_cannot_change_boundaries() -> None:
    act = _case(685)
    invalid = replace(act, target_effective_from=date(2013, 1, 25))
    with pytest.raises(ValueError, match="cannot change boundaries"):
        plan_membership_adjudication(
            _blockers(),
            cases=_replace_case(invalid),
            live_siblings=_siblings(),
        )


def test_correction_requires_a_real_boundary_change() -> None:
    wcg = _case(814)
    invalid = replace(
        wcg,
        target_effective_from=wcg.prior_effective_from,
        target_effective_to=wcg.prior_effective_to,
    )
    with pytest.raises(ValueError, match="must change a boundary"):
        plan_membership_adjudication(
            _blockers(),
            cases=_replace_case(invalid),
            live_siblings=_siblings(),
        )


def test_duplicate_cover_is_rejection_only() -> None:
    ua_c = _case(834)
    invalid = replace(ua_c, action="verify")
    with pytest.raises(ValueError, match="duplicate cover only supports rejection"):
        plan_membership_adjudication(
            _blockers(),
            cases=_replace_case(invalid),
            live_siblings=_siblings(),
        )


def test_ua_c_is_rejected_against_verified_class_c_cover() -> None:
    decisions = plan_membership_adjudication(
        _blockers(),
        cases=HU5_MEMBERSHIP_ADJUDICATION_CASES,
        live_siblings=_siblings(),
    )
    decision = next(item for item in decisions if item.membership_id == 834)
    assert decision.action == "reject"
    assert decision.sibling_membership_ids == (833,)


def test_viac_is_shortened_exactly_to_para_successor_start() -> None:
    decision = next(
        item
        for item in plan_membership_adjudication(
            _blockers(),
            cases=HU5_MEMBERSHIP_ADJUDICATION_CASES,
            live_siblings=_siblings(),
        )
        if item.membership_id == 638
    )
    assert decision.action == "correct_and_verify"
    assert decision.target_effective_to == date(2022, 2, 17)
    assert decision.sibling_membership_ids == (267, 637)


def test_wpx_uses_session_aware_boundaries() -> None:
    decision = next(
        item
        for item in plan_membership_adjudication(
            _blockers(),
            cases=HU5_MEMBERSHIP_ADJUDICATION_CASES,
            live_siblings=_siblings(),
        )
        if item.membership_id == 899
    )
    assert decision.target_effective_from == date(2012, 1, 3)
    assert decision.target_effective_to == date(2014, 3, 24)
