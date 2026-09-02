from __future__ import annotations

from datetime import date

import pytest

from fdre.research.historical_universe_lineage import TickerMembershipLineage
from fdre.research.historical_universe_state_support import (
    ProvisionalStateInterval,
    corroborated_source_hash,
    plan_state_support,
    state_support_plan_id,
)


def _interval(
    *,
    row_id: int = 1,
    start: date = date(2012, 1, 2),
    end: date | None = date(2014, 5, 6),
    symbol: str = "ABC",
) -> ProvisionalStateInterval:
    return ProvisionalStateInterval(
        row_kind="membership",
        row_id=row_id,
        security_id=11,
        cik="0000000001",
        symbol=symbol,
        effective_from=start,
        effective_to=end,
        source="lawcal/sp500-components-history",
        source_hash="a" * 64,
    )


def _lineage(
    *,
    start: date = date(2010, 1, 1),
    end: date | None = date(2015, 1, 1),
    symbol: str = "ABC",
) -> TickerMembershipLineage:
    return TickerMembershipLineage(
        symbol=symbol,
        effective_from=start,
        effective_to=end,
        source="fja05680/sp500-ticker-start-end",
        source_ref="pinned-ref",
        source_hash="b" * 64,
    )


def test_full_containment_supports_state_without_rewriting_boundaries() -> None:
    decision = plan_state_support((_interval(),), (_lineage(),))[0]

    assert decision.status == "fully_supported"
    assert decision.promotable is True
    assert decision.lineage_effective_from == date(2010, 1, 1)
    assert decision.lineage_effective_to == date(2015, 1, 1)


def test_partial_overlap_stays_provisional() -> None:
    decision = plan_state_support(
        (_interval(end=date(2015, 1, 2)),),
        (_lineage(),),
    )[0]

    assert decision.status == "partial"
    assert decision.promotable is False


def test_open_interval_requires_open_independent_state() -> None:
    decision = plan_state_support(
        (_interval(end=None),),
        (_lineage(end=date(2026, 1, 1)),),
    )[0]

    assert decision.status == "partial"
    assert decision.promotable is False


def test_reused_ticker_multiple_containing_intervals_fails_closed() -> None:
    interval = _interval(start=date(2012, 1, 2), end=date(2012, 2, 1))
    decision = plan_state_support(
        (interval,),
        (
            _lineage(start=date(2010, 1, 1), end=date(2015, 1, 1)),
            _lineage(start=date(2011, 1, 1), end=date(2014, 1, 1)),
        ),
    )[0]

    assert decision.status == "ambiguous"
    assert decision.promotable is False


def test_symbol_normalization_is_exact_not_fuzzy() -> None:
    decision = plan_state_support(
        (_interval(symbol="BRK.B"),),
        (_lineage(symbol="BRK-B"),),
    )[0]

    assert decision.status == "fully_supported"


def test_plan_and_corroborated_hash_are_replay_deterministic() -> None:
    decisions = plan_state_support((_interval(),), (_lineage(),))
    replay = plan_state_support((_interval(),), (_lineage(),))

    assert state_support_plan_id(decisions) == state_support_plan_id(replay)
    plan_id = state_support_plan_id(decisions)
    assert corroborated_source_hash(decisions[0], plan_id=plan_id) == (
        corroborated_source_hash(replay[0], plan_id=plan_id)
    )


def test_duplicate_target_rows_fail_closed() -> None:
    with pytest.raises(ValueError, match="duplicate provisional state row"):
        plan_state_support((_interval(), _interval()), (_lineage(),))
