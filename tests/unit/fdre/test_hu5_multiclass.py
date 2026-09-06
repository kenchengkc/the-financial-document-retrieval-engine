from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from fdre.research import hu5_multiclass as multiclass
from fdre.research.event_study import EventStudyConfig, EventWindow, FilingEvent, MarketBar
from fdre.research.historical_universe import (
    SecurityIdentityRecord,
    UniverseMembershipRecord,
)
from fdre.research.hu5_universe import HU5UniverseRecords, build_hu5_universe_gate


def _membership(security_id: int) -> UniverseMembershipRecord:
    return UniverseMembershipRecord(
        universe_code="sp500",
        security_id=security_id,
        effective_from=date(2020, 1, 1),
        effective_to=None,
        source_hash=f"membership-{security_id}",
        verification_status="verified",
    )


def _identity(security_id: int, cik: str, symbol: str) -> SecurityIdentityRecord:
    return SecurityIdentityRecord(
        security_id=security_id,
        cik=cik,
        symbol=symbol,
        effective_from=date(2020, 1, 1),
        effective_to=None,
        source_hash=f"identity-{security_id}",
        verification_status="verified",
    )


def _event() -> FilingEvent:
    return FilingEvent(
        ticker="CURRENT",
        accession_number="0001-20-000001",
        available_at=datetime(2020, 6, 1, 12, tzinfo=UTC),
        max_source_available_at=datetime(2020, 6, 1, 12, tzinfo=UTC),
        feature_value=1.0,
    )


def test_multiclass_resolver_keeps_one_issuer_observation_and_all_lineage() -> None:
    records = HU5UniverseRecords(
        memberships=(_membership(1), _membership(2)),
        identities=(
            _identity(1, "0000000001", "AAA"),
            _identity(2, "0000000001", "AAB"),
        ),
    )
    gate = build_hu5_universe_gate(
        records,
        universe_code="sp500",
        window_start=date(2020, 6, 1),
        window_end=date(2020, 6, 1),
    )
    event = _event()

    resolved = multiclass.resolve_hu5_events_multiclass(
        [event],
        cik_by_accession={event.accession_number: "0000000001"},
        records=records,
        gate=gate,
    )

    assert len(resolved.events) == 1
    assert resolved.events[0].ticker == "CIK-0000000001"
    assert len(resolved.lineage) == 2
    assert resolved.multiclass_event_count == 1
    assert not resolved.unresolved_accessions
    mapping = resolved.outcome_mappings[0]
    assert mapping.symbols == ("AAA", "AAB")
    assert mapping.observation_ticker == "CIK-0000000001"
    assert mapping.is_multiclass is True
    assert resolved.outcome_mapping_id
    assert resolved.universe_lineage_id


def test_single_class_resolver_preserves_existing_historical_symbol() -> None:
    records = HU5UniverseRecords(
        memberships=(_membership(1),),
        identities=(_identity(1, "0000000001", "OLD"),),
    )
    gate = build_hu5_universe_gate(
        records,
        universe_code="sp500",
        window_start=date(2020, 6, 1),
        window_end=date(2020, 6, 1),
    )
    event = _event()

    resolved = multiclass.resolve_hu5_events_multiclass(
        [event],
        cik_by_accession={event.accession_number: "0000000001"},
        records=records,
        gate=gate,
    )

    assert resolved.events[0].ticker == "OLD"
    assert resolved.outcome_mappings[0].symbols == ("OLD",)
    assert resolved.outcome_mappings[0].is_multiclass is False


def test_multiclass_outcome_is_equal_weight_mean_then_benchmark_adjusted() -> None:
    event = _event().model_copy(update={"ticker": "CIK-0000000001"})
    mapping = multiclass.HU5EventOutcomeMapping(
        accession_number=event.accession_number,
        as_of="2020-06-01",
        snapshot_id="snapshot",
        cik="0000000001",
        observation_ticker=event.ticker,
        components=(
            multiclass.HU5OutcomeComponent(1, "AAA", "m1", "i1"),
            multiclass.HU5OutcomeComponent(2, "AAB", "m2", "i2"),
        ),
    )
    config = EventStudyConfig(
        benchmark_ticker="SPY",
        windows=[EventWindow(start=1, end=2)],
        bootstrap_iterations=100,
    )
    bars = [
        MarketBar(ticker="SPY", date=date(2020, 6, 1), adjusted_close=100),
        MarketBar(ticker="SPY", date=date(2020, 6, 2), adjusted_close=100),
        MarketBar(ticker="SPY", date=date(2020, 6, 3), adjusted_close=110),
        MarketBar(ticker="AAA", date=date(2020, 6, 2), adjusted_close=100),
        MarketBar(ticker="AAA", date=date(2020, 6, 3), adjusted_close=120),
        MarketBar(ticker="AAB", date=date(2020, 6, 2), adjusted_close=200),
        MarketBar(ticker="AAB", date=date(2020, 6, 3), adjusted_close=220),
    ]

    outcomes = multiclass._multi_class_event_returns(
        [event],
        bars,
        config,
        {event.accession_number: mapping},
    )

    assert len(outcomes) == 1
    assert outcomes[0].asset_return == pytest.approx(0.15)
    assert outcomes[0].benchmark_return == pytest.approx(0.10)
    assert outcomes[0].abnormal_return == pytest.approx(0.05)
    assert outcomes[0].ticker == "CIK-0000000001"


def test_missing_component_endpoint_fails_without_renormalization() -> None:
    event = _event().model_copy(update={"ticker": "CIK-0000000001"})
    mapping = multiclass.HU5EventOutcomeMapping(
        accession_number=event.accession_number,
        as_of="2020-06-01",
        snapshot_id="snapshot",
        cik="0000000001",
        observation_ticker=event.ticker,
        components=(
            multiclass.HU5OutcomeComponent(1, "AAA", "m1", "i1"),
            multiclass.HU5OutcomeComponent(2, "AAB", "m2", "i2"),
        ),
    )
    config = EventStudyConfig(
        benchmark_ticker="SPY",
        windows=[EventWindow(start=1, end=2)],
        bootstrap_iterations=100,
    )
    bars = [
        MarketBar(ticker="SPY", date=date(2020, 6, 1), adjusted_close=100),
        MarketBar(ticker="SPY", date=date(2020, 6, 2), adjusted_close=100),
        MarketBar(ticker="SPY", date=date(2020, 6, 3), adjusted_close=110),
        MarketBar(ticker="AAA", date=date(2020, 6, 2), adjusted_close=100),
        MarketBar(ticker="AAA", date=date(2020, 6, 3), adjusted_close=120),
        MarketBar(ticker="AAB", date=date(2020, 6, 2), adjusted_close=200),
    ]

    with pytest.raises(multiclass.HU5MultiClassOutcomeUnavailableError) as caught:
        multiclass._multi_class_event_returns(
            [event],
            bars,
            config,
            {event.accession_number: mapping},
        )

    assert len(caught.value.issues) == 1
    assert caught.value.issues[0].reason == "component_endpoint_unavailable"
    assert caught.value.issues[0].missing_symbols == ("AAB",)
