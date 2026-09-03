from __future__ import annotations

from datetime import date

from fdre.research.historical_universe_membership_continuity import (
    CurrentConstituentAnchor,
    VerifiedSiblingMembership,
    plan_membership_continuity,
)
from fdre.research.historical_universe_strict_coverage import (
    IdentityContext,
    ProvisionalMembershipBlocker,
)


def _blocker(
    *,
    membership_id: int = 1,
    security_id: int = 10,
    cik: str = "0000000123",
    start: date = date(2020, 1, 2),
    end: date | None = None,
    symbol: str = "NEW",
) -> ProvisionalMembershipBlocker:
    return ProvisionalMembershipBlocker(
        membership_id=membership_id,
        security_id=security_id,
        cik=cik,
        effective_from=start,
        effective_to=end,
        source="lawcal",
        source_url=None,
        source_hash="a" * 64,
        confidence=0.5,
        identities=(
            IdentityContext(
                symbol=symbol,
                effective_from=start,
                effective_to=end,
                verification_status="verified",
                source_hash="b" * 64,
            ),
        ),
    )


def _anchor(
    *,
    symbol: str = "NEW",
    cik: str = "0000000123",
    added: date = date(2010, 1, 4),
) -> CurrentConstituentAnchor:
    return CurrentConstituentAnchor(
        symbol=symbol,
        cik=cik,
        date_added=added,
        source_ref="c" * 40,
        source_hash="d" * 64,
        row_hash="e" * 64,
    )


def _sibling(
    *,
    membership_id: int = 2,
    security_id: int = 20,
    cik: str = "0000000123",
    start: date = date(2010, 1, 1),
    end: date | None = None,
) -> VerifiedSiblingMembership:
    return VerifiedSiblingMembership(
        membership_id=membership_id,
        security_id=security_id,
        cik=cik,
        effective_from=start,
        effective_to=end,
        source_hash="f" * 64,
    )


def test_open_membership_uses_exact_current_cik_symbol_anchor() -> None:
    decision = plan_membership_continuity(
        (_blocker(),),
        current_anchors=(_anchor(),),
        verified_siblings=(),
    )[0]
    assert decision.action == "verify"
    assert decision.method == "current_constituent_anchor"
    assert len(decision.evidence_ids) == 1


def test_current_anchor_after_interval_start_fails_closed() -> None:
    decision = plan_membership_continuity(
        (_blocker(),),
        current_anchors=(_anchor(added=date(2021, 1, 1)),),
        verified_siblings=(),
    )[0]
    assert decision.action == "unresolved"


def test_current_anchor_requires_exact_active_symbol() -> None:
    decision = plan_membership_continuity(
        (_blocker(symbol="OLD"),),
        current_anchors=(_anchor(symbol="NEW"),),
        verified_siblings=(),
    )[0]
    assert decision.action == "unresolved"


def test_closed_interval_rejects_only_when_one_verified_sibling_covers_all() -> None:
    blocker = _blocker(end=date(2021, 1, 1))
    decision = plan_membership_continuity(
        (blocker,),
        current_anchors=(),
        verified_siblings=(_sibling(),),
    )[0]
    assert decision.action == "reject"
    assert decision.method == "single_verified_sibling_cover"


def test_partial_sibling_cover_fails_closed() -> None:
    blocker = _blocker(end=date(2021, 1, 1))
    decision = plan_membership_continuity(
        (blocker,),
        current_anchors=(),
        verified_siblings=(_sibling(end=date(2020, 6, 1)),),
    )[0]
    assert decision.action == "unresolved"


def test_two_covering_sibling_securities_preserve_share_class_ambiguity() -> None:
    blocker = _blocker(end=date(2021, 1, 1))
    decision = plan_membership_continuity(
        (blocker,),
        current_anchors=(),
        verified_siblings=(
            _sibling(membership_id=2, security_id=20),
            _sibling(membership_id=3, security_id=30),
        ),
    )[0]
    assert decision.action == "unresolved"
    assert "share-class ambiguity" in decision.reason


def test_same_security_is_not_a_sibling_cover() -> None:
    blocker = _blocker(end=date(2021, 1, 1))
    decision = plan_membership_continuity(
        (blocker,),
        current_anchors=(),
        verified_siblings=(_sibling(security_id=blocker.security_id),),
    )[0]
    assert decision.action == "unresolved"


def test_plan_is_deterministic() -> None:
    blockers = (
        _blocker(membership_id=2, security_id=11),
        _blocker(membership_id=1, security_id=10),
    )
    anchors = (_anchor(),)
    first = plan_membership_continuity(
        blockers,
        current_anchors=anchors,
        verified_siblings=(),
    )
    second = plan_membership_continuity(
        tuple(reversed(blockers)),
        current_anchors=anchors,
        verified_siblings=(),
    )
    assert first == second
