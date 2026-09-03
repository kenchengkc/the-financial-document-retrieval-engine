from __future__ import annotations

from datetime import date

import pytest
from scripts.research.historical_universe.historical_universe_sec_identity_apply import (
    PROJECTION_SCHEMA_VERSION,
    _decision_hash,
    _projection_plan_id,
    _stage_candidates,
    _validate_apply_request,
    _validate_projection,
    corroborated_identity_source_hash,
)

from apps.api.app.models import Company
from apps.api.app.models.historical_universe import (
    Security,
    SecurityIdentityEvidence,
    SecurityIdentityPeriod,
)
from fdre.research.historical_universe_sec_identity import SecTradingSymbolEvidence


def _evidence() -> SecTradingSymbolEvidence:
    return SecTradingSymbolEvidence(
        row_id=7,
        cik="0000000001",
        accession_number="0000000001-13-000001",
        filing_date=date(2013, 2, 1),
        form_type="10-K",
        symbol="ABC",
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1/000000000113000001/report.htm"
        ),
        payload_sha256="b" * 64,
        concept_name="dei:TradingSymbol",
        context_ref="c1",
    )


def _decision(evidence_id: str) -> dict[str, object]:
    decision: dict[str, object] = {
        "row_id": 7,
        "security_id": 11,
        "cik": "0000000001",
        "symbol": "ABC",
        "effective_from": "2012-01-02",
        "effective_to": "2014-05-06",
        "prior_source_hash": "a" * 64,
        "status": "fully_supported",
        "state_decision_hash": "d" * 64,
        "state_lineage_id": "e" * 64,
        "sec_evidence_ids": [evidence_id],
        "conflicting_accessions": [],
        "inspected_accessions": ["0000000001-13-000001"],
        "reason": "test",
        "promotion_candidate": True,
    }
    decision["decision_hash"] = _decision_hash(decision)
    return decision


def _projection() -> tuple[dict[str, object], str, SecTradingSymbolEvidence]:
    evidence = _evidence()
    decision = _decision(evidence.evidence_id)
    decisions = (decision,)
    plan_id = _projection_plan_id(decisions)
    payload: dict[str, object] = {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "mode": "projection",
        "applied": False,
        "plan_id": plan_id,
        "filing_error_count": 0,
        "sec_evidence_count": 1,
        "status_counts": {"fully_supported": 1},
        "promotion_candidate_count": 1,
        "evidence": [evidence.as_dict()],
        "decisions": [decision],
    }
    return payload, plan_id, evidence


def test_apply_requires_explicit_production_opt_in() -> None:
    with pytest.raises(RuntimeError, match="FDRE_ALLOW_PROD=1"):
        _validate_apply_request(
            apply=True,
            expected_plan_id="a" * 64,
            allow_prod=False,
        )


def test_apply_requires_explicit_apply_flag() -> None:
    with pytest.raises(RuntimeError, match="explicit --apply"):
        _validate_apply_request(
            apply=False,
            expected_plan_id="a" * 64,
            allow_prod=True,
        )


def test_projection_validation_recomputes_plan_and_evidence_hashes() -> None:
    payload, plan_id, evidence = _projection()

    candidates, evidence_by_id = _validate_projection(
        payload,
        expected_plan_id=plan_id,
        expected_promotion_count=1,
    )

    assert len(candidates) == 1
    assert evidence_by_id[evidence.evidence_id] == evidence


def test_projection_validation_rejects_tampered_decision() -> None:
    payload, plan_id, _ = _projection()
    decisions = payload["decisions"]
    assert isinstance(decisions, list)
    decision = decisions[0]
    assert isinstance(decision, dict)
    decision["symbol"] = "XYZ"

    with pytest.raises(RuntimeError, match="decision hash mismatch"):
        _validate_projection(
            payload,
            expected_plan_id=plan_id,
            expected_promotion_count=1,
        )


def test_projection_validation_rejects_filing_errors() -> None:
    payload, plan_id, _ = _projection()
    payload["filing_error_count"] = 1

    with pytest.raises(RuntimeError, match="fetch/extraction errors"):
        _validate_projection(
            payload,
            expected_plan_id=plan_id,
            expected_promotion_count=1,
        )


class _SessionStub:
    def __init__(
        self,
        identity: SecurityIdentityPeriod,
        security: Security,
        company: Company,
        *,
        existing_evidence: tuple[str, ...] = (),
    ) -> None:
        self.identity = identity
        self.security = security
        self.company = company
        self.existing_evidence = existing_evidence
        self.added: list[SecurityIdentityEvidence] = []
        self.flushed = False

    def get(self, model: type[object], row_id: int) -> object | None:
        if model is SecurityIdentityPeriod:
            return self.identity if row_id == self.identity.id else None
        if model is Security:
            return self.security if row_id == self.security.id else None
        if model is Company:
            return self.company if row_id == self.company.id else None
        raise AssertionError(f"unexpected model {model}")

    def scalars(self, _statement: object) -> tuple[str, ...]:
        return self.existing_evidence

    def add(self, value: object) -> None:
        assert isinstance(value, SecurityIdentityEvidence)
        self.added.append(value)

    def flush(self) -> None:
        self.flushed = True


def _session() -> _SessionStub:
    identity = SecurityIdentityPeriod(
        id=7,
        security_id=11,
        symbol="ABC",
        effective_from=date(2012, 1, 2),
        effective_to=date(2014, 5, 6),
        source="lawcal/sp500-components-history",
        source_hash="a" * 64,
        verification_status="provisional",
        confidence=0.80,
    )
    security = Security(id=11, company_id=3)
    company = Company(id=3, cik="0000000001", ticker="ABC", name="Example Corp")
    return _SessionStub(identity, security, company)


def test_stage_promotes_exact_row_and_persists_only_referenced_evidence() -> None:
    payload, plan_id, evidence = _projection()
    candidates, evidence_by_id = _validate_projection(
        payload,
        expected_plan_id=plan_id,
        expected_promotion_count=1,
    )
    session = _session()

    update_count, evidence_count, rows = _stage_candidates(
        session,  # type: ignore[arg-type]
        candidates,
        evidence_by_id,
        plan_id=plan_id,
    )

    assert update_count == 1
    assert evidence_count == 1
    assert session.flushed is True
    assert session.identity.verification_status == "verified"
    assert session.identity.confidence == pytest.approx(0.98)
    assert session.identity.source.endswith("+sec/xbrl-symbol+fja05680/sp500-state")
    assert session.identity.source_hash != "a" * 64
    assert len(session.identity.source_hash) == 64
    assert len(session.added) == 1
    persisted = session.added[0]
    assert persisted.evidence_id == evidence.evidence_id
    assert persisted.security_identity_period_id == 7
    assert persisted.projection_plan_id == plan_id
    assert rows[0]["sec_evidence_ids"] == [evidence.evidence_id]


def test_stage_rejects_live_source_hash_drift() -> None:
    payload, plan_id, _ = _projection()
    candidates, evidence_by_id = _validate_projection(
        payload,
        expected_plan_id=plan_id,
        expected_promotion_count=1,
    )
    session = _session()
    session.identity.source_hash = "f" * 64

    with pytest.raises(RuntimeError, match="source hash changed"):
        _stage_candidates(
            session,  # type: ignore[arg-type]
            candidates,
            evidence_by_id,
            plan_id=plan_id,
        )


def test_stage_rejects_live_issuer_cik_drift() -> None:
    payload, plan_id, _ = _projection()
    candidates, evidence_by_id = _validate_projection(
        payload,
        expected_plan_id=plan_id,
        expected_promotion_count=1,
    )
    session = _session()
    session.company.cik = "0000000002"

    with pytest.raises(RuntimeError, match="issuer CIK changed"):
        _stage_candidates(
            session,  # type: ignore[arg-type]
            candidates,
            evidence_by_id,
            plan_id=plan_id,
        )


def test_source_hash_is_deterministic_and_plan_bound() -> None:
    payload, plan_id, evidence = _projection()
    decisions = payload["decisions"]
    assert isinstance(decisions, list)
    decision = decisions[0]
    assert isinstance(decision, dict)

    first = corroborated_identity_source_hash(decision, plan_id=plan_id)
    replay = corroborated_identity_source_hash(decision, plan_id=plan_id)
    changed_plan = corroborated_identity_source_hash(decision, plan_id="f" * 64)

    assert first == replay
    assert first != changed_plan
    assert evidence.evidence_id in decision["sec_evidence_ids"]
