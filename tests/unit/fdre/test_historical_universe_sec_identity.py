from __future__ import annotations

from datetime import date

import pytest

from fdre.research.historical_universe_lineage import TickerMembershipLineage
from fdre.research.historical_universe_sec_identity import (
    SecIdentityFilingObservation,
    extract_trading_symbols,
    filing_directory_index_url,
    plan_sec_identity_support,
    sec_identity_plan_id,
    xbrl_instance_filenames,
)
from fdre.research.historical_universe_state_support import (
    ProvisionalStateInterval,
    plan_state_support,
)


def _interval(*, row_id: int = 1, symbol: str = "ABC") -> ProvisionalStateInterval:
    return ProvisionalStateInterval(
        row_kind="identity",
        row_id=row_id,
        security_id=11,
        cik="0000000001",
        symbol=symbol,
        effective_from=date(2012, 1, 2),
        effective_to=date(2014, 5, 6),
        source="lawcal/sp500-components-history",
        source_hash="a" * 64,
    )


def _lineage(
    *,
    symbol: str = "ABC",
    end: date | None = date(2015, 1, 1),
) -> TickerMembershipLineage:
    return TickerMembershipLineage(
        symbol=symbol,
        effective_from=date(2010, 1, 1),
        effective_to=end,
        source="fja05680/sp500-ticker-start-end",
        source_ref="pinned-ref",
        source_hash="b" * 64,
    )


def _observation(
    *,
    row_id: int = 1,
    symbols: tuple[str, ...] = ("ABC",),
    accession: str = "0000000001-13-000001",
) -> SecIdentityFilingObservation:
    return SecIdentityFilingObservation(
        row_id=row_id,
        accession_number=accession,
        filing_date=date(2013, 2, 1),
        form_type="10-K",
        symbols=tuple(sorted(symbols)),
        evidence_ids=("c" * 64,) if symbols else (),
        inspected_urls=(
            "https://www.sec.gov/Archives/edgar/data/1/000000000113000001/report.htm",
        ),
    )


def test_extracts_inline_xbrl_trading_symbol_only() -> None:
    payload = b"""
    <html><body>
      <div>Trading Symbol: WRONG</div>
      <ix:nonNumeric name="dei:TradingSymbol" contextRef="c1">brk.b</ix:nonNumeric>
      <ix:nonNumeric name="dei:EntityRegistrantName" contextRef="c1">Example Corp</ix:nonNumeric>
    </body></html>
    """

    assert extract_trading_symbols(payload) == (("BRK-B", "dei:TradingSymbol", "c1"),)


def test_extracts_classic_xbrl_trading_symbol_element() -> None:
    payload = b"""<?xml version="1.0"?>
    <xbrl xmlns:dei="http://xbrl.sec.gov/dei/2013-01-31">
      <dei:TradingSymbol contextRef="d2013">ABC</dei:TradingSymbol>
    </xbrl>
    """

    facts = extract_trading_symbols(payload)
    assert len(facts) == 1
    assert facts[0][0] == "ABC"
    assert facts[0][2] == "d2013"


def test_free_text_trading_symbol_label_is_not_evidence() -> None:
    assert extract_trading_symbols("<html><body>Trading Symbol: ABC</body></html>") == ()


def test_sec_directory_url_is_strict() -> None:
    assert filing_directory_index_url(
        "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm"
    ) == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/index.json"
    )
    with pytest.raises(ValueError, match=r"www\.sec\.gov"):
        filing_directory_index_url("https://example.com/report.htm")


def test_instance_candidates_exclude_linkbases_and_reports() -> None:
    payload: dict[str, object] = {
        "directory": {
            "item": [
                {"name": "abc-20121231.xml", "size": "12000"},
                {"name": "abc-20121231_cal.xml", "size": "9000"},
                {"name": "abc-20121231_pre.xml", "size": "8000"},
                {"name": "FilingSummary.xml", "size": "7000"},
                {"name": "R1.xml", "size": "6000"},
                {"name": "other.xml", "size": "1000"},
            ]
        }
    }

    assert xbrl_instance_filenames(payload) == ("abc-20121231.xml", "other.xml")


def test_exact_sec_symbol_plus_full_state_is_promotion_candidate() -> None:
    interval = _interval()
    states = plan_state_support((interval,), (_lineage(),))
    decision = plan_sec_identity_support((interval,), states, (_observation(),))[0]

    assert decision.status == "fully_supported"
    assert decision.promotion_candidate is True
    assert decision.sec_evidence_ids == ("c" * 64,)


def test_conflicting_sec_symbol_fails_closed() -> None:
    interval = _interval()
    states = plan_state_support((interval,), (_lineage(),))
    decision = plan_sec_identity_support(
        (interval,),
        states,
        (_observation(symbols=("XYZ",)),),
    )[0]

    assert decision.status == "sec_symbol_conflict"
    assert decision.promotion_candidate is False


def test_missing_sec_symbol_stays_provisional() -> None:
    interval = _interval()
    states = plan_state_support((interval,), (_lineage(),))
    decision = plan_sec_identity_support(
        (interval,),
        states,
        (_observation(symbols=()),),
    )[0]

    assert decision.status == "sec_symbol_missing"
    assert decision.promotion_candidate is False


def test_partial_state_cannot_be_repaired_by_sec_filing() -> None:
    interval = _interval()
    states = plan_state_support((interval,), (_lineage(end=date(2013, 1, 1)),))
    decision = plan_sec_identity_support((interval,), states, (_observation(),))[0]

    assert decision.status == "state_not_fully_supported"
    assert decision.promotion_candidate is False


def test_identity_projection_plan_is_replay_deterministic() -> None:
    interval = _interval()
    states = plan_state_support((interval,), (_lineage(),))
    first = plan_sec_identity_support((interval,), states, (_observation(),))
    replay = plan_sec_identity_support((interval,), states, (_observation(),))

    assert sec_identity_plan_id(first) == sec_identity_plan_id(replay)


def test_duplicate_identity_rows_fail_closed() -> None:
    interval = _interval()
    states = plan_state_support((interval,), (_lineage(),))
    with pytest.raises(ValueError, match="duplicate provisional identity row"):
        plan_sec_identity_support((interval, interval), states, (_observation(),))
