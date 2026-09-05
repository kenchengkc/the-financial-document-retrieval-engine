from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from scripts.research.historical_universe import (
    historical_universe_identity_adjudication_apply as writer,
)
from scripts.research.historical_universe.historical_universe_identity_adjudication_projection import (  # noqa: E501
    stage_identity_actions,
)
from sqlalchemy import Table, create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company
from apps.api.app.models.historical_universe import (
    Security,
    SecurityIdentityPeriod,
    UniverseMembership,
)
from fdre.research.historical_universe_identity_adjudication import (
    EXPECTED_IDENTITY_ADJUDICATION_MANIFEST_ID,
    EXPECTED_IDENTITY_ADJUDICATION_PLAN_ID,
    EXPECTED_TOPOLOGY_AUDIT_ID,
    EXPECTED_TOPOLOGY_ID,
    IdentityAdjudicationCase,
    IdentityAnchor,
    IdentityEvidence,
    MembershipAnchor,
)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    for model in (Company, Security, SecurityIdentityPeriod, UniverseMembership):
        cast(Table, model.__table__).create(engine)
    with Session(engine) as db:
        db.add(Company(id=1, cik="0000000001", name="Test issuer"))
        db.add(Security(id=1, company_id=1))
        db.add(
            SecurityIdentityPeriod(
                id=1,
                security_id=1,
                symbol="OLD",
                effective_from=date(2020, 1, 1),
                effective_to=None,
                source="fixture",
                source_hash="a" * 64,
                source_observed_at=datetime(2020, 1, 1, tzinfo=UTC),
                verification_status="provisional",
                confidence=0.85,
            )
        )
        db.add(
            UniverseMembership(
                id=1,
                security_id=1,
                universe_code="sp500",
                effective_from=date(2020, 1, 1),
                effective_to=None,
                source="fixture",
                source_hash="b" * 64,
                source_observed_at=datetime(2020, 1, 1, tzinfo=UTC),
                verification_status="verified",
                confidence=0.99,
            )
        )
        db.commit()
        yield db
    engine.dispose()


def _cases() -> tuple[IdentityAdjudicationCase, ...]:
    membership = MembershipAnchor(
        membership_id=1,
        security_id=1,
        cik="0000000001",
        universe_code="sp500",
        effective_from=date(2020, 1, 1),
        effective_to=None,
        verification_status="verified",
        source_hash="b" * 64,
    )
    evidence = IdentityEvidence("issuer", "https://example.test/transition", "Same stock.")
    correction = IdentityAdjudicationCase(
        case_id="correct-old",
        action="correct_and_verify",
        security_id=1,
        cik="0000000001",
        symbol="OLD",
        existing_identity_id=1,
        prior_effective_from=date(2020, 1, 1),
        prior_effective_to=None,
        prior_source_hash="a" * 64,
        prior_verification_status="provisional",
        target_effective_from=date(2020, 1, 1),
        target_effective_to=date(2020, 2, 1),
        membership_anchors=(membership,),
        evidence=(evidence,),
        reason="End old ticker.",
    )
    successor = IdentityAdjudicationCase(
        case_id="insert-new",
        action="insert",
        security_id=1,
        cik="0000000001",
        symbol="NEW",
        target_effective_from=date(2020, 2, 1),
        target_effective_to=None,
        name="Test issuer",
        exchange="NYSE",
        evidence=(evidence,),
        reason="Successor ticker.",
        membership_anchors=(membership,),
        identity_anchors=(
            IdentityAnchor(
                identity_id=1,
                security_id=1,
                cik="0000000001",
                symbol="OLD",
                effective_from=date(2020, 1, 1),
                effective_to=None,
                verification_status="provisional",
                source_hash="a" * 64,
            ),
        ),
    )
    return correction, successor


def test_real_staging_corrects_before_inserting_and_rolls_back(session: Session) -> None:
    changes = stage_identity_actions(
        session,
        _cases(),
        manifest_id="m",
        plan_id="p",
        projection=True,
    )
    assert len(changes) == 2
    rows = list(
        session.scalars(
            select(SecurityIdentityPeriod).order_by(SecurityIdentityPeriod.effective_from)
        )
    )
    assert [(row.symbol, row.effective_from, row.effective_to) for row in rows] == [
        ("OLD", date(2020, 1, 1), date(2020, 2, 1)),
        ("NEW", date(2020, 2, 1), None),
    ]
    assert rows[1].id < 0
    assert all(row.verification_status == "verified" for row in rows)
    session.rollback()
    original = session.get(SecurityIdentityPeriod, 1)
    assert original is not None
    assert original.effective_to is None and original.verification_status == "provisional"
    assert list(session.scalars(select(SecurityIdentityPeriod.id))) == [1]


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_hash", "c" * 64),
        ("symbol", "DRIFT"),
        ("effective_from", date(2020, 1, 2)),
        ("security_id", 2),
    ],
)
def test_live_row_drift_prevents_any_staging(
    session: Session,
    field: str,
    value: Any,
) -> None:
    row = session.get(SecurityIdentityPeriod, 1)
    assert row is not None
    if field == "security_id":
        session.add(Security(id=2, company_id=1))
    setattr(row, field, value)
    session.commit()
    with pytest.raises(RuntimeError, match="drifted"):
        stage_identity_actions(session, _cases(), manifest_id="m", plan_id="p", projection=False)
    assert row.verification_status == "provisional"


def test_live_issuer_cik_drift_is_rejected(session: Session) -> None:
    company = session.get(Company, 1)
    assert company is not None
    company.cik = "0000000002"
    session.commit()
    with pytest.raises(RuntimeError, match="issuer CIK drifted"):
        stage_identity_actions(session, _cases(), manifest_id="m", plan_id="p", projection=False)


def test_missing_membership_sibling_fails_before_staging(session: Session) -> None:
    sibling = session.get(UniverseMembership, 1)
    assert sibling is not None
    session.delete(sibling)
    session.commit()
    with pytest.raises(RuntimeError, match="membership anchor 1 disappeared"):
        stage_identity_actions(session, _cases(), manifest_id="m", plan_id="p", projection=False)


def test_live_insert_overlap_is_rejected(session: Session) -> None:
    correction, successor = _cases()
    successor = replace(successor, target_effective_from=date(2020, 1, 31))
    with pytest.raises(RuntimeError, match="overlaps live identities"):
        stage_identity_actions(
            session,
            (correction, successor),
            manifest_id="m",
            plan_id="p",
            projection=False,
        )
    session.rollback()
    row = session.get(SecurityIdentityPeriod, 1)
    assert row is not None and row.effective_to is None


@pytest.mark.parametrize("failure", [None, "gate", "audit", "provenance", "stage"])
def test_apply_commits_only_after_all_checks(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    # Substitute the expensive frozen replay; exercise a real DB transaction and mutation.
    # Gate/manifest replay correctness is covered by their separate unit suites.
    before = SimpleNamespace(as_dict=lambda: {"audit_id": "before"})
    after = SimpleNamespace(as_dict=lambda: {"audit_id": "after"})
    gate_before = SimpleNamespace(gate_manifest_id="before", input_provenance_id="before")
    gate_after = SimpleNamespace(
        gate_manifest_id=writer.EXPECTED_POST_GATE_ID,
        input_provenance_id=writer.EXPECTED_POST_PROVENANCE_ID,
    )
    events: list[str] = []
    monkeypatch.setattr(writer, "_lock_inputs", lambda db: events.append("lock"))
    monkeypatch.setattr(
        writer, "build_live_residual_identity_topology", lambda *a, **kw: (None, before)
    )
    monkeypatch.setattr(writer, "_topology_payload", lambda *a: {})
    monkeypatch.setattr(writer, "build_hu5_identity_adjudication_cases", lambda **kw: ())
    monkeypatch.setattr(writer, "validate_identity_adjudication_projection", lambda *a, **kw: ())
    monkeypatch.setattr(writer, "_require_pre_state", lambda *a: events.append("pre"))
    gates = iter((gate_before, gate_after))
    monkeypatch.setattr(writer, "_current_gate", lambda db: next(gates))
    monkeypatch.setattr(
        writer, "_gate_payload", lambda gate: {"gate_manifest_id": gate.gate_manifest_id}
    )
    monkeypatch.setattr(writer, "_current_identity_audit", lambda db: after)

    def stage(db: Session, *args: Any, **kwargs: Any) -> list[dict[str, str]]:
        events.append("stage")
        db.execute(text("UPDATE security_identity_periods SET verification_status = 'verified'"))
        if failure == "stage":
            raise RuntimeError("stage failed")
        return [{"case_id": str(index)} for index in range(45)]

    def check(*args: Any) -> None:
        events.append("post")
        if failure in {"gate", "audit"}:
            raise RuntimeError(f"{failure} failed")

    monkeypatch.setattr(writer, "stage_identity_actions", stage)
    monkeypatch.setattr(writer, "require_closed_post_state", check)
    payload = {
        "strict_coverage_before": {"gate_manifest_id": "before"},
        "identity_strict_coverage_before": before.as_dict(),
        "strict_coverage_projected": {
            "gate_manifest_id": (
                "tampered" if failure == "provenance" else writer.EXPECTED_POST_GATE_ID
            )
        },
        "decisions": [],
        "reviewed_evidence": [],
    }
    if failure:
        with pytest.raises(RuntimeError):
            writer.apply_identity_adjudication(session, residual_sec={}, projection=payload)
    else:
        result = writer.apply_identity_adjudication(session, residual_sec={}, projection=payload)
        assert result["transaction_committed"] is True
        assert events == ["lock", "pre", "stage", "post"]
    row = session.get(SecurityIdentityPeriod, 1)
    assert row is not None
    assert row.verification_status == ("provisional" if failure else "verified")


def test_apply_requires_explicit_flags_and_exact_frozen_ids() -> None:
    request = {
        "apply": True,
        "allow_prod": True,
        "expected_manifest_id": EXPECTED_IDENTITY_ADJUDICATION_MANIFEST_ID,
        "expected_plan_id": EXPECTED_IDENTITY_ADJUDICATION_PLAN_ID,
        "expected_audit_id": EXPECTED_TOPOLOGY_AUDIT_ID,
        "expected_topology_id": EXPECTED_TOPOLOGY_ID,
    }
    writer._validate_request(**request)  # type: ignore[arg-type]
    for field in request:
        invalid = {**request, field: False if field in {"apply", "allow_prod"} else "0" * 64}
        with pytest.raises(RuntimeError):
            writer._validate_request(**invalid)  # type: ignore[arg-type]


def test_postgres_input_locks_block_concurrent_writes_until_rollback() -> None:
    database_url = os.environ.get("FDRE_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("FDRE_POSTGRES_TEST_URL is required for PostgreSQL locking test")
    engine = create_db_engine(database_url)
    schema = "hu5_lock_test_" + uuid4().hex
    tables = (
        "companies",
        "securities",
        "security_identity_periods",
        "universe_memberships",
        "security_identity_evidence",
    )
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            for table in tables:
                connection.execute(text(f'CREATE TABLE "{schema}".{table} (id integer)'))
        with Session(engine) as first:
            first.execute(text(f'SET LOCAL search_path = "{schema}"'))
            writer._lock_inputs(first)
            for table in tables:
                with engine.connect() as second:
                    second.execute(text("SET LOCAL lock_timeout = '100ms'"))
                    with pytest.raises(OperationalError, match="lock timeout"):
                        second.execute(text(f'INSERT INTO "{schema}".{table} VALUES (1)'))
                    second.rollback()
            first.rollback()
        with engine.begin() as connection:
            for table in tables:
                connection.execute(text(f'INSERT INTO "{schema}".{table} VALUES (1)'))
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
