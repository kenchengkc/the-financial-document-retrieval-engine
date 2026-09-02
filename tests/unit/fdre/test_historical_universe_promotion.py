from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from scripts.historical_universe_promote import (
    AnchorConstituentExpectation,
    AnchorExpectation,
    BoundaryVerification,
    CurrentIssuer,
    _identity_claims,
    _load_current,
    _membership_verified,
    materialize,
    validate_materialized_state,
)
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app.db import Base
from apps.api.app.models.companies import Company
from apps.api.app.models.historical_universe import (
    Security,
    SecurityIdentityPeriod,
    UniverseMembership,
)
from fdre.research.historical_component_history import HistoricalComponentRecord

_OBSERVED_AT = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def _engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _record(
    *,
    start: date,
    end: date | None,
    added_approximate: bool = False,
    removed_approximate: bool = False,
    created_at: date | None = None,
) -> HistoricalComponentRecord:
    return HistoricalComponentRecord(
        symbol="ABC",
        cik="0000000001",
        name="Alpha Corp",
        sector="industrials",
        effective_from=start,
        effective_to=end,
        created_at=created_at or start,
        added_approximate=added_approximate,
        removed_approximate=removed_approximate,
        source_ref="a" * 40,
        source_hash="b" * 64,
    )


def test_membership_verification_requires_exact_independent_interval() -> None:
    record = _record(start=date(2012, 1, 2), end=date(2014, 5, 6))
    intervals: set[tuple[str, date, date | None]] = {
        ("ABC", date(2012, 1, 2), date(2014, 5, 6))
    }
    assert _membership_verified(record, intervals) is True
    assert _membership_verified(record, set()) is False


def test_approximate_source_dates_remain_provisional() -> None:
    record = _record(
        start=date(2012, 1, 2),
        end=date(2014, 5, 6),
        added_approximate=True,
    )
    intervals: set[tuple[str, date, date | None]] = {
        ("ABC", date(2012, 1, 2), date(2014, 5, 6))
    }
    assert _membership_verified(record, intervals) is False


def test_exact_independent_interval_supports_later_serialized_membership() -> None:
    record = _record(
        start=date(2012, 1, 2),
        end=date(2014, 5, 6),
        created_at=date(2013, 2, 3),
    )
    intervals: set[tuple[str, date, date | None]] = {
        ("ABC", date(2012, 1, 2), date(2014, 5, 6))
    }

    assert _membership_verified(record, intervals) is True
    claims = _identity_claims([record], frozenset({record.record_id}))
    assert claims[0].effective_from == date(2012, 1, 2)


def test_materialization_uses_exact_independent_identity_start() -> None:
    start = date(2010, 1, 1)
    created = date(2015, 6, 1)
    record = _record(start=start, end=None, created_at=created)
    engine = _engine()

    with Session(engine) as session:
        plan = materialize(
            session,
            records=(record,),
            current_by_cik={},
            verified_intervals={("ABC", start, None)},
            observed_at=_OBSERVED_AT,
            stage=True,
        )
        identity = session.scalar(select(SecurityIdentityPeriod))
        membership = session.scalar(select(UniverseMembership))
        identity_start = identity.effective_from if identity is not None else None
        membership_start = membership.effective_from if membership is not None else None
        session.rollback()

    assert plan.source_validity_adjusted_memberships == 0
    assert plan.verified_memberships == 1
    assert plan.provisional_memberships == 0
    assert identity_start == start
    assert membership_start == start


def test_cross_source_boundary_adjudication_can_verify_an_exact_identity_span() -> None:
    record = _record(
        start=date(2012, 1, 2),
        end=date(2014, 5, 6),
        added_approximate=True,
    )
    verification = BoundaryVerification(
        audit_id="d" * 64,
        verified_record_ids=frozenset({record.record_id}),
    )
    engine = _engine()

    with Session(engine) as session:
        plan = materialize(
            session,
            records=(record,),
            current_by_cik={},
            verified_intervals=set(),
            observed_at=_OBSERVED_AT,
            stage=True,
            boundary_verification=verification,
        )
        membership = session.scalar(select(UniverseMembership))
        membership_status = (
            membership.verification_status if membership is not None else None
        )
        membership_source = membership.source if membership is not None else None
        session.rollback()

    assert plan.verified_memberships == 1
    assert plan.cross_source_boundary_verified_memberships == 1
    assert membership_status == "verified"
    assert membership_source == (
        "lawcal/sp500-components-history+cross-source-boundary-adjudication"
    )


def test_identity_remains_valid_on_removal_boundary_only() -> None:
    claims = _identity_claims(
        [_record(start=date(2012, 1, 2), end=date(2014, 5, 6))]
    )
    assert len(claims) == 1
    assert claims[0].effective_from == date(2012, 1, 2)
    assert claims[0].effective_to == date(2014, 5, 7)


def test_open_component_membership_produces_open_identity() -> None:
    claims = _identity_claims(
        [_record(start=date(2020, 1, 2), end=None)]
    )
    assert len(claims) == 1
    assert claims[0].effective_from == date(2020, 1, 2)
    assert claims[0].effective_to is None


def test_disjoint_index_tenures_do_not_create_unobserved_identity_bridge() -> None:
    claims = _identity_claims(
        [
            _record(start=date(2010, 1, 1), end=date(2012, 1, 1)),
            _record(start=date(2015, 1, 1), end=date(2018, 1, 1)),
        ]
    )

    assert [(claim.effective_from, claim.effective_to) for claim in claims] == [
        (date(2010, 1, 1), date(2012, 1, 2)),
        (date(2015, 1, 1), date(2018, 1, 2)),
    ]


def test_current_company_primary_ticker_is_deterministic_for_share_classes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "current.csv"
    path.write_text(
        "symbol,cik,name,sector\n"
        "ZZZ,0000000001,Alpha Corp,industrials\n"
        "AAA,0000000001,Alpha Corp,industrials\n",
        encoding="utf-8",
    )
    current = _load_current(path)
    assert current["0000000001"].symbol == "AAA"


def test_current_xom_holding_company_cik_is_corrected(tmp_path: Path) -> None:
    path = tmp_path / "current.csv"
    path.write_text(
        "symbol,cik,name,sector\n"
        "XOM,0002115436,ExxonMobil,energy\n",
        encoding="utf-8",
    )

    current = _load_current(path)

    assert current["0000034088"].symbol == "XOM"
    assert "0002115436" not in current


def test_dry_run_rejects_current_ticker_owned_by_another_cik() -> None:
    records, _, intervals = _materialization_inputs()
    engine = _engine()

    with Session(engine) as session:
        session.add(
            Company(
                ticker="ABC",
                cik="0000000002",
                name="Existing Ticker Owner",
            )
        )
        session.commit()

        with pytest.raises(ValueError, match="already belongs to production CIK"):
            materialize(
                session,
                records=records,
                current_by_cik={
                    records[0].cik: CurrentIssuer(
                        symbol="ABC",
                        cik=records[0].cik,
                        name=records[0].name,
                        sector=records[0].sector,
                    )
                },
                verified_intervals=intervals,
                observed_at=_OBSERVED_AT,
                stage=False,
            )


def _materialization_inputs(
    *,
    verified: bool = True,
) -> tuple[
    tuple[HistoricalComponentRecord, ...],
    dict[str, CurrentIssuer],
    set[tuple[str, date, date | None]],
]:
    start = date(2010, 1, 1)
    record = _record(start=start, end=None)
    intervals: set[tuple[str, date, date | None]] = (
        {("ABC", start, None)} if verified else set()
    )
    return (
        (record,),
        {
            record.cik: CurrentIssuer(
                symbol="ABC",
                cik=record.cik,
                name=record.name,
                sector=record.sector,
            )
        },
        intervals,
    )


def _anchor(symbol: str = "ABC") -> AnchorExpectation:
    return AnchorExpectation(
        anchor_id="test-anchor",
        universe_code="sp500",
        effective_at=date(2020, 1, 1),
        constituents=(
            AnchorConstituentExpectation(
                cik="0000000001",
                symbol=symbol,
                name="Alpha Corp",
                membership_effective_to=None,
                source_hash="e" * 64,
            ),
        ),
    )


def test_staged_materialization_validates_and_is_idempotent() -> None:
    records, current, intervals = _materialization_inputs()
    engine = _engine()

    with Session(engine) as session:
        first = materialize(
            session,
            records=records,
            current_by_cik=current,
            verified_intervals=intervals,
            observed_at=_OBSERVED_AT,
            stage=True,
        )
        validation = validate_materialized_state(session, _anchor())
        assert validation.commit_eligible is True
        session.commit()

        second = materialize(
            session,
            records=records,
            current_by_cik=current,
            verified_intervals=intervals,
            observed_at=_OBSERVED_AT,
            stage=True,
        )
        replay_validation = validate_materialized_state(session, _anchor())
        session.commit()

        assert first.membership_creates == 1
        assert second.historical_company_creates == 0
        assert second.current_company_creates == 0
        assert second.security_creates == 0
        assert second.identity_creates == 0
        assert second.membership_creates == 0
        assert replay_validation.commit_eligible is True
        assert int(session.scalar(select(func.count()).select_from(Company)) or 0) == 1
        assert int(session.scalar(select(func.count()).select_from(Security)) or 0) == 1
        assert (
            int(
                session.scalar(
                    select(func.count()).select_from(SecurityIdentityPeriod)
                )
                or 0
            )
            == 1
        )
        assert (
            int(session.scalar(select(func.count()).select_from(UniverseMembership)) or 0)
            == 1
        )


def test_failed_anchor_validation_rolls_back_every_staged_row() -> None:
    records, current, intervals = _materialization_inputs()
    engine = _engine()

    with Session(engine) as session:
        materialize(
            session,
            records=records,
            current_by_cik=current,
            verified_intervals=intervals,
            observed_at=_OBSERVED_AT,
            stage=True,
        )
        validation = validate_materialized_state(session, _anchor("XYZ"))
        assert validation.commit_eligible is False
        assert validation.missing_anchor_symbols == ("0000000001/XYZ",)
        assert validation.unexpected_snapshot_symbols == ("0000000001/ABC",)
        session.rollback()

        assert int(session.scalar(select(func.count()).select_from(Company)) or 0) == 0
        assert int(session.scalar(select(func.count()).select_from(Security)) or 0) == 0
        assert (
            int(session.scalar(select(func.count()).select_from(UniverseMembership)) or 0)
            == 0
        )


def test_provisional_materialization_cannot_pass_strict_validation() -> None:
    records, current, intervals = _materialization_inputs(verified=False)
    engine = _engine()

    with Session(engine) as session:
        materialize(
            session,
            records=records,
            current_by_cik=current,
            verified_intervals=intervals,
            observed_at=_OBSERVED_AT,
            stage=True,
        )
        validation = validate_materialized_state(session, _anchor())
        session.rollback()

    assert validation.provisional_anchor_match is True
    assert validation.strict_anchor_match is False
    assert validation.strict_snapshot_error is not None
    assert "active provisional membership" in validation.strict_snapshot_error
    assert validation.commit_eligible is False


def test_dry_run_planning_does_not_stage_rows() -> None:
    records, current, intervals = _materialization_inputs()
    engine = _engine()

    with Session(engine) as session:
        plan = materialize(
            session,
            records=records,
            current_by_cik=current,
            verified_intervals=intervals,
            observed_at=_OBSERVED_AT,
            stage=False,
        )

        assert plan.current_company_creates == 1
        assert plan.security_creates == 1
        assert plan.identity_creates == 1
        assert plan.membership_creates == 1
        assert int(session.scalar(select(func.count()).select_from(Company)) or 0) == 0
        assert int(session.scalar(select(func.count()).select_from(Security)) or 0) == 0
        assert (
            int(session.scalar(select(func.count()).select_from(UniverseMembership)) or 0)
            == 0
        )
