from __future__ import annotations

from datetime import date

import pytest
from scripts.research.historical_universe.historical_universe_state_support import (
    _stage_decisions,
    _validate_apply_request,
)

from apps.api.app.models.historical_universe import UniverseMembership
from fdre.research.historical_universe_lineage import TickerMembershipLineage
from fdre.research.historical_universe_state_support import (
    ProvisionalStateInterval,
    StateSupportDecision,
    plan_state_support,
    state_support_plan_id,
)


def _decision() -> StateSupportDecision:
    interval = ProvisionalStateInterval(
        row_kind="membership",
        row_id=7,
        security_id=11,
        cik="0000000001",
        symbol="ABC",
        effective_from=date(2012, 1, 2),
        effective_to=date(2014, 5, 6),
        source="lawcal/sp500-components-history",
        source_hash="a" * 64,
    )
    lineage = TickerMembershipLineage(
        symbol="ABC",
        effective_from=date(2010, 1, 1),
        effective_to=date(2015, 1, 1),
        source="fja05680/sp500-ticker-start-end",
        source_ref="pinned-ref",
        source_hash="b" * 64,
    )
    return plan_state_support((interval,), (lineage,))[0]


def test_apply_requires_explicit_production_opt_in() -> None:
    with pytest.raises(RuntimeError, match="FDRE_ALLOW_PROD=1"):
        _validate_apply_request(
            apply=True,
            expected_plan_id="plan",
            plan_id="plan",
            allow_prod=False,
        )


def test_apply_requires_exact_replay_plan_id() -> None:
    with pytest.raises(RuntimeError, match="state-support plan changed"):
        _validate_apply_request(
            apply=True,
            expected_plan_id="old-plan",
            plan_id="new-plan",
            allow_prod=True,
        )


def test_projection_rejects_apply_only_plan_argument() -> None:
    with pytest.raises(RuntimeError, match="requires --apply"):
        _validate_apply_request(
            apply=False,
            expected_plan_id="plan",
            plan_id="plan",
            allow_prod=False,
        )


class _SessionStub:
    def __init__(self, membership: UniverseMembership) -> None:
        self.membership = membership
        self.flushed = False

    def get(
        self,
        model: type[UniverseMembership],
        row_id: int,
    ) -> UniverseMembership:
        assert model is UniverseMembership
        assert row_id == self.membership.id
        return self.membership

    def flush(self) -> None:
        self.flushed = True


def test_stage_promotes_only_exact_supported_membership_with_hashed_provenance() -> None:
    decision = _decision()
    decisions = (decision,)
    plan_id = state_support_plan_id(decisions)
    membership = UniverseMembership(
        id=7,
        universe_code="sp500",
        security_id=11,
        effective_from=date(2012, 1, 2),
        effective_to=date(2014, 5, 6),
        source="lawcal/sp500-components-history",
        source_hash="a" * 64,
        verification_status="provisional",
        confidence=0.85,
    )
    session = _SessionStub(membership)

    membership_updates, identity_updates = _stage_decisions(
        session,  # type: ignore[arg-type]
        decisions,
        plan_id=plan_id,
    )

    assert membership_updates == 1
    assert identity_updates == 0
    assert session.flushed is True
    assert membership.verification_status == "verified"
    assert membership.confidence == pytest.approx(0.98)
    assert membership.source.endswith("+fja05680/sp500-state-corroboration")
    assert membership.source_hash != "a" * 64
    assert len(membership.source_hash) == 64
