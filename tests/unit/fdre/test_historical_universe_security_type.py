from __future__ import annotations

import pytest

from fdre.research.historical_universe_security_type import (
    SecurityTypeAdjudicationTarget,
    extract_schering_plough_preferred_evidence,
    plan_security_type_adjudication,
    security_symbol_key,
    security_type_plan_id,
)

SEC_URL = (
    "https://www.sec.gov/Archives/edgar/data/310158/000095012307011295/y37189bte424b2.htm"
)


def _payload() -> bytes:
    return b"""
    <html><body>
      <p>Schering-Plough is offering 10,000,000 shares of 6.00% mandatory convertible
      preferred stock, referred to as the 2007 Preferred Stock.</p>
      <p>The 2007 Preferred Stock has been approved for listing on the New York Stock
      Exchange, subject to issuance, under the symbol &quot;SGP PrB.&quot;</p>
      <p>Schering-Plough's common shares are listed on the New York Stock Exchange under
      the symbol &quot;SGP.&quot;</p>
    </body></html>
    """


def _target(
    *,
    row_kind: str = "membership",
    symbol: str = "SGPPRB",
    cik: str = "0000310158",
    status: str = "provisional",
) -> SecurityTypeAdjudicationTarget:
    assert row_kind in {"membership", "identity"}
    return SecurityTypeAdjudicationTarget(
        row_kind=row_kind,  # type: ignore[arg-type]
        row_id=580 if row_kind == "membership" else 581,
        security_id=798,
        cik=cik,
        symbol=symbol,
        prior_source_hash="a" * 64,
        verification_status=status,
    )


def test_symbol_key_only_removes_presentation_separators() -> None:
    assert security_symbol_key("SGP PrB") == "SGPPRB"
    assert security_symbol_key("SGP.PRB") == "SGPPRB"
    assert security_symbol_key("SGP") == "SGP"


def test_extracts_explicit_preferred_and_distinct_common_symbol() -> None:
    evidence = extract_schering_plough_preferred_evidence(_payload(), source_url=SEC_URL)

    assert evidence.cik == "0000310158"
    assert evidence.listed_symbol == "SGPPRB"
    assert evidence.security_type == "preferred_stock"
    assert evidence.common_symbol == "SGP"
    assert len(evidence.payload_sha256) == 64
    assert len(evidence.evidence_id) == 64


def test_free_text_ticker_shape_is_not_security_type_evidence() -> None:
    with pytest.raises(ValueError, match="does not explicitly bind"):
        extract_schering_plough_preferred_evidence(
            b"<html><body>Ticker: SGPPRB</body></html>",
            source_url=SEC_URL,
        )


def test_exact_membership_and_identity_rows_are_rejection_candidates() -> None:
    evidence = extract_schering_plough_preferred_evidence(_payload(), source_url=SEC_URL)
    decisions = plan_security_type_adjudication(
        (_target(), _target(row_kind="identity")),
        evidence,
    )

    assert [item.status for item in decisions] == [
        "reject_non_common_security",
        "reject_non_common_security",
    ]
    assert all(item.rejection_candidate for item in decisions)
    assert all(item.evidence_id == evidence.evidence_id for item in decisions)


def test_cik_symbol_or_status_mismatch_fails_closed() -> None:
    evidence = extract_schering_plough_preferred_evidence(_payload(), source_url=SEC_URL)
    decisions = plan_security_type_adjudication(
        (
            _target(symbol="SGP"),
            _target(cik="0000310159"),
            _target(status="verified"),
        ),
        evidence,
    )

    assert all(item.status == "unresolved" for item in decisions)
    assert not any(item.rejection_candidate for item in decisions)
    assert all(item.evidence_id is None for item in decisions)


def test_security_type_plan_is_replay_deterministic() -> None:
    evidence = extract_schering_plough_preferred_evidence(_payload(), source_url=SEC_URL)
    targets = (_target(), _target(row_kind="identity"))

    first = plan_security_type_adjudication(targets, evidence)
    replay = plan_security_type_adjudication(targets, evidence)

    assert security_type_plan_id(first) == security_type_plan_id(replay)
