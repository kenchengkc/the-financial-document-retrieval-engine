from __future__ import annotations

from datetime import date

import pytest

from fdre.research.historical_universe_residual_sec_evidence import (
    ResidualSecTarget,
    plan_residual_sec_evidence,
    residual_sec_plan_id,
)
from fdre.research.historical_universe_sec_identity import SecIdentityFilingObservation


def _target(*, identity_id: int = 1, symbol: str = "ABC") -> ResidualSecTarget:
    return ResidualSecTarget(
        identity_id=identity_id,
        security_id=10 + identity_id,
        cik=f"{identity_id:010d}",
        symbol=symbol,
        effective_from=date(2020, 1, 1),
        effective_to=date(2021, 1, 1),
        source_hash=f"{identity_id:064x}",
    )


def _observation(
    *,
    identity_id: int = 1,
    accession: str = "0000000001-20-000001",
    facts: tuple[tuple[str, str], ...] = (("ABC", "evidence-abc"),),
    error: str | None = None,
) -> SecIdentityFilingObservation:
    return SecIdentityFilingObservation(
        row_id=identity_id,
        accession_number=accession,
        filing_date=date(2020, 6, 1),
        form_type="10-Q",
        facts=tuple(sorted(facts)),
        inspected_urls=("https://www.sec.gov/Archives/example.htm",),
        error=error,
    )


def test_exact_sec_symbol_supports_target() -> None:
    decision = plan_residual_sec_evidence((_target(),), (_observation(),))[0]
    assert decision.status == "sec_supported"
    assert decision.sec_evidence_ids == ("evidence-abc",)
    assert decision.supported is True


def test_share_class_punctuation_uses_existing_match_semantics() -> None:
    target = _target(symbol="BF-B")
    observation = _observation(facts=(("BFB", "evidence-bfb"),))
    decision = plan_residual_sec_evidence((target,), (observation,))[0]
    assert decision.status == "sec_supported"
    assert decision.sec_evidence_ids == ("evidence-bfb",)


def test_only_matching_fact_contributes_evidence() -> None:
    observation = _observation(
        facts=(("ABC", "evidence-abc"), ("ABC 29", "evidence-debt"))
    )
    decision = plan_residual_sec_evidence((_target(),), (observation,))[0]
    assert decision.status == "sec_supported"
    assert decision.sec_evidence_ids == ("evidence-abc",)


def test_nonempty_excluding_symbol_is_conflict() -> None:
    observation = _observation(facts=(("XYZ", "evidence-xyz"),))
    decision = plan_residual_sec_evidence((_target(),), (observation,))[0]
    assert decision.status == "sec_symbol_conflict"
    assert decision.conflicting_accessions == (observation.accession_number,)


def test_fetch_error_fails_closed_even_with_other_matching_filing() -> None:
    good = _observation(accession="0000000001-20-000001")
    failed = _observation(
        accession="0000000001-20-000002",
        facts=(),
        error="TimeoutError: source unavailable",
    )
    decision = plan_residual_sec_evidence((_target(),), (good, failed))[0]
    assert decision.status == "sec_fetch_error"
    assert decision.error_accessions == (failed.accession_number,)


def test_no_explicit_fact_stays_missing() -> None:
    observation = _observation(facts=())
    decision = plan_residual_sec_evidence((_target(),), (observation,))[0]
    assert decision.status == "sec_symbol_missing"


def test_unknown_observation_target_fails_closed() -> None:
    with pytest.raises(ValueError, match="outside the frozen target set"):
        plan_residual_sec_evidence((_target(),), (_observation(identity_id=2),))


def test_duplicate_targets_fail_closed() -> None:
    target = _target()
    with pytest.raises(ValueError, match="must be unique"):
        plan_residual_sec_evidence((target, target), ())


def test_plan_id_is_input_order_independent() -> None:
    target_a = _target(identity_id=1, symbol="AAA")
    target_b = _target(identity_id=2, symbol="BBB")
    observations = (
        _observation(identity_id=1, facts=(("AAA", "evidence-a"),)),
        _observation(identity_id=2, facts=(("BBB", "evidence-b"),)),
    )
    first = plan_residual_sec_evidence((target_b, target_a), tuple(reversed(observations)))
    second = plan_residual_sec_evidence((target_a, target_b), observations)
    assert first == second
    assert residual_sec_plan_id(first, topology_id="f" * 64) == residual_sec_plan_id(
        second,
        topology_id="f" * 64,
    )
