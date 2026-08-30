from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models.companies import Company
from apps.api.app.models.historical_universe import (
    Security,
    SecurityIdentityPeriod,
    UniverseMembership,
)
from fdre.universe import snapshot_to_dict, universe_from_session, write_universe_snapshot

OBSERVED_AT = datetime(2026, 8, 30, 16, 0, tzinfo=UTC)


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_security(
    session: Session,
    *,
    security_id: int,
    ticker: str,
    cik: str,
    membership_from: date,
    membership_to: date | None = None,
    status: str = "verified",
) -> None:
    company = Company(
        id=security_id,
        ticker=ticker,
        cik=cik,
        name=f"{ticker} Corp",
        exchange="NYSE",
    )
    security = Security(id=security_id, company=company, security_type="common_stock")
    identity = SecurityIdentityPeriod(
        id=security_id,
        security=security,
        symbol=ticker,
        name=f"{ticker} Corp",
        exchange="NYSE",
        effective_from=membership_from,
        effective_to=membership_to,
        source="test-identity",
        source_url="https://example.test/identity",
        source_observed_at=OBSERVED_AT,
        source_hash=(f"{security_id:064d}"[-64:]),
        verification_status=status,
        confidence=1.0,
    )
    membership = UniverseMembership(
        id=security_id,
        universe_code="sp500",
        security=security,
        effective_from=membership_from,
        effective_to=membership_to,
        source="test-membership",
        source_url="https://example.test/membership",
        source_observed_at=OBSERVED_AT,
        source_hash=(f"{security_id + 1000:064d}"[-64:]),
        verification_status=status,
        confidence=1.0,
    )
    session.add_all((company, security, identity, membership))
    session.commit()


def test_db_query_is_point_in_time_and_replay_deterministic() -> None:
    with _session() as session:
        _seed_security(
            session,
            security_id=1,
            ticker="OLD",
            cik="0000000001",
            membership_from=date(2015, 1, 1),
            membership_to=date(2020, 3, 20),
        )
        _seed_security(
            session,
            security_id=2,
            ticker="NEW",
            cik="0000000002",
            membership_from=date(2020, 3, 20),
        )

        before = universe_from_session(session, "SP500", as_of="2020-03-19")
        on_change = universe_from_session(session, "sp500", as_of=date(2020, 3, 20))
        replay = universe_from_session(session, "sp500", as_of="2020-03-20")

        assert [row.symbol for row in before.constituents] == ["OLD"]
        assert [row.symbol for row in on_change.constituents] == ["NEW"]
        assert on_change.snapshot_id == replay.snapshot_id
        assert on_change.snapshot_id != before.snapshot_id


def test_future_membership_cannot_leak_into_past_db_query() -> None:
    with _session() as session:
        _seed_security(
            session,
            security_id=1,
            ticker="LATE",
            cik="0000000001",
            membership_from=date(2023, 1, 1),
        )

        snapshot = universe_from_session(session, "sp500", as_of="2020-01-01")

        assert snapshot.constituents == ()


def test_provisional_db_rows_fail_closed_unless_explicitly_included() -> None:
    with _session() as session:
        _seed_security(
            session,
            security_id=1,
            ticker="ABC",
            cik="0000000001",
            membership_from=date(2020, 1, 1),
            status="provisional",
        )

        with pytest.raises(ValueError, match="active provisional membership"):
            universe_from_session(session, "sp500", as_of="2021-01-01")

        snapshot = universe_from_session(
            session,
            "sp500",
            as_of="2021-01-01",
            include_provisional=True,
        )
        assert [row.symbol for row in snapshot.constituents] == ["ABC"]
        assert snapshot.constituents[0].verification_status == "provisional"


def test_json_export_preserves_snapshot_and_source_hashes(tmp_path: Path) -> None:
    with _session() as session:
        _seed_security(
            session,
            security_id=1,
            ticker="ABC",
            cik="0000000001",
            membership_from=date(2020, 1, 1),
        )
        snapshot = universe_from_session(session, "sp500", as_of="2021-01-01")

    output = write_universe_snapshot(snapshot, tmp_path / "snapshot.json")
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload == snapshot_to_dict(snapshot)
    assert payload["snapshot_id"] == snapshot.snapshot_id
    constituent = payload["constituents"][0]
    assert len(constituent["membership_source_hash"]) == 64
    assert len(constituent["identity_source_hash"]) == 64


def test_parquet_export_is_row_addressable_and_carries_snapshot_metadata(
    tmp_path: Path,
) -> None:
    pyarrow = pytest.importorskip("pyarrow.parquet")
    with _session() as session:
        _seed_security(
            session,
            security_id=1,
            ticker="ABC",
            cik="0000000001",
            membership_from=date(2020, 1, 1),
        )
        snapshot = universe_from_session(session, "sp500", as_of="2021-01-01")

    output = write_universe_snapshot(snapshot, tmp_path / "snapshot.parquet")
    table = pyarrow.read_table(output)

    assert table.num_rows == 1
    assert table.column("symbol").to_pylist() == ["ABC"]
    assert table.schema.metadata[b"fdre_snapshot_id"].decode() == snapshot.snapshot_id
