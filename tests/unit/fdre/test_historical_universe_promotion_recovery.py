from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models.companies import Company
from apps.api.app.models.operation_receipts import OperationReceipt
from fdre.research.historical_universe import promotion, promotion_cli


def _source_args(tmp_path: Path) -> list[str]:
    paths: dict[str, Path] = {}
    for name in (
        "component-history",
        "current-components",
        "ticker-lineages",
        "anchor",
        "boundary-audit",
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(f"{name}\n", encoding="utf-8")
        paths[name] = path
    return [
        "--component-history",
        str(paths["component-history"]),
        "--component-history-ref",
        "component-ref",
        "--current-components",
        str(paths["current-components"]),
        "--ticker-lineages",
        str(paths["ticker-lineages"]),
        "--ticker-lineages-ref",
        "lineage-ref",
        "--anchor",
        str(paths["anchor"]),
        "--boundary-audit",
        str(paths["boundary-audit"]),
        "--observed-at",
        "2026-09-13T17:00:00Z",
    ]


def _plan() -> promotion.MaterializationPlan:
    return promotion.MaterializationPlan(
        anchor_security_count=1,
        historical_company_creates=0,
        current_company_creates=1,
        current_ticker_fills=0,
        security_creates=0,
        identity_creates=0,
        membership_creates=0,
        verified_memberships=0,
        provisional_memberships=0,
        source_validity_adjusted_memberships=0,
        cross_source_boundary_verified_memberships=0,
        source_interval_count=1,
        exact_independent_interval_count=1,
        plan_hash="f" * 64,
    )


def test_post_commit_report_failure_recovers_without_reapplying(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "promotion.sqlite"
    database_url = f"sqlite+pysqlite:///{database}"
    engine = create_engine(database_url)
    Company.__table__.create(engine)
    OperationReceipt.__table__.create(engine)
    engine.dispose()

    anchor = promotion.AnchorExpectation(
        anchor_id="anchor",
        universe_code="sp500",
        effective_at=promotion.date(2026, 9, 1),
        constituents=(),
    )
    boundary = promotion.BoundaryVerification(audit_id="a" * 64, verified_record_ids=frozenset())
    monkeypatch.setattr(
        promotion_cli,
        "_load_inputs",
        lambda args: ((), {}, set(), anchor, boundary),
    )
    materialize_calls = 0

    def materialize(session: Session, **kwargs: object) -> promotion.MaterializationPlan:
        nonlocal materialize_calls
        del kwargs
        materialize_calls += 1
        session.add(Company(ticker="ABC", cik="0000000001", name="Alpha Corp"))
        return _plan()

    validation = SimpleNamespace(
        commit_eligible=True,
        as_dict=lambda: {"commit_eligible": True, "anchor_id": "anchor"},
    )
    monkeypatch.setattr(promotion, "materialize", materialize)
    monkeypatch.setattr(promotion, "validate_materialized_state", lambda *args: validation)

    def fail_export(path: Path, payload: dict[str, object]) -> None:
        del path, payload
        raise OSError("simulated report export failure")

    monkeypatch.setattr(promotion_cli, "_write_report", fail_export)
    output = tmp_path / "apply.json"
    argv = [
        "--database-url",
        database_url,
        *_source_args(tmp_path),
        "--apply",
        "--operation-id",
        "hu2-2026-09-13",
        "--output",
        str(output),
    ]

    with pytest.raises(OSError, match="simulated report export failure"):
        promotion_cli.main(argv)

    check_engine = create_engine(database_url)
    with Session(check_engine) as session:
        assert int(session.scalar(select(func.count()).select_from(Company)) or 0) == 1
        receipt = session.get(OperationReceipt, "hu2-2026-09-13")
        assert receipt is not None
        assert receipt.payload_json["applied"] is True
    check_engine.dispose()
    assert materialize_calls == 1

    def forbid_reapply(session: Session, **kwargs: object) -> promotion.MaterializationPlan:
        del session, kwargs
        raise AssertionError("materialization must not run when a committed receipt exists")

    monkeypatch.setattr(promotion, "materialize", forbid_reapply)

    def write_report(path: Path, payload: dict[str, object]) -> None:
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    monkeypatch.setattr(promotion_cli, "_write_report", write_report)
    assert promotion_cli.main(argv) == 0
    assert materialize_calls == 1
    recovered_payload = json.loads(output.read_text(encoding="utf-8"))
    assert recovered_payload["operation_id"] == "hu2-2026-09-13"

    recovered_output = tmp_path / "recovered.json"
    assert (
        promotion_cli.main(
            [
                "--database-url",
                database_url,
                "--recover-operation-id",
                "hu2-2026-09-13",
                "--output",
                str(recovered_output),
            ]
        )
        == 0
    )
    assert json.loads(recovered_output.read_text(encoding="utf-8")) == recovered_payload

    final_engine = create_engine(database_url)
    with Session(final_engine) as session:
        assert int(session.scalar(select(func.count()).select_from(Company)) or 0) == 1
    final_engine.dispose()


def test_operation_id_reuse_with_different_inputs_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "reuse.sqlite"
    database_url = f"sqlite+pysqlite:///{database}"
    engine = create_engine(database_url)
    OperationReceipt.__table__.create(engine)
    with Session(engine) as session:
        payload: dict[str, object] = {"applied": True, "operation_id": "same-id"}
        session.add(
            OperationReceipt(
                operation_id="same-id",
                operation_type=promotion_cli._OPERATION_TYPE,
                request_sha256="0" * 64,
                payload_sha256=promotion_cli._hash_json(payload),
                payload_json=payload,
            )
        )
        session.commit()
    engine.dispose()

    monkeypatch.setattr(
        promotion_cli,
        "_load_inputs",
        lambda args: pytest.fail("input parsing should not run before receipt request validation"),
    )
    argv = [
        "--database-url",
        database_url,
        *_source_args(tmp_path),
        "--apply",
        "--operation-id",
        "same-id",
        "--output",
        str(tmp_path / "unused.json"),
    ]
    with pytest.raises(RuntimeError, match="different request"):
        promotion_cli.main(argv)


def test_postgres_receipt_is_atomic_with_mutation() -> None:
    database_url = os.environ.get("FDRE_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("FDRE_POSTGRES_TEST_URL is required for PostgreSQL receipt test")
    engine = create_db_engine(database_url)
    schema = "operation_receipt_test_" + uuid4().hex
    payload: dict[str, object] = {"applied": True, "operation_id": "committed"}
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(
                text(
                    f'CREATE TABLE "{schema}".operation_receipts ('
                    "operation_id varchar(128) PRIMARY KEY, "
                    "operation_type varchar(64) NOT NULL, "
                    "request_sha256 varchar(64) NOT NULL, "
                    "payload_sha256 varchar(64) NOT NULL, "
                    "payload_json json NOT NULL, "
                    "created_at timestamptz NOT NULL DEFAULT now())"
                )
            )
            connection.execute(
                text(
                    f'CREATE TABLE "{schema}".mutation_counter '
                    "(id integer PRIMARY KEY, value integer NOT NULL)"
                )
            )
            connection.execute(
                text(f'INSERT INTO "{schema}".mutation_counter VALUES (1, 0)')
            )

        with Session(engine) as session:
            session.execute(text(f'SET LOCAL search_path = "{schema}"'))
            session.execute(text("UPDATE mutation_counter SET value = value + 1 WHERE id = 1"))
            promotion_cli._stage_receipt(
                session,
                operation_id="rolled-back",
                request_sha256="a" * 64,
                payload=payload,
            )
            session.rollback()

        with Session(engine) as session:
            session.execute(text(f'SET LOCAL search_path = "{schema}"'))
            assert session.scalar(text("SELECT value FROM mutation_counter WHERE id = 1")) == 0
            assert promotion_cli._load_receipt(session, "rolled-back") is None
            session.rollback()

        with Session(engine) as session:
            session.execute(text(f'SET LOCAL search_path = "{schema}"'))
            session.execute(text("UPDATE mutation_counter SET value = value + 1 WHERE id = 1"))
            promotion_cli._stage_receipt(
                session,
                operation_id="committed",
                request_sha256="b" * 64,
                payload=payload,
            )
            session.commit()

        with Session(engine) as session:
            session.execute(text(f'SET LOCAL search_path = "{schema}"'))
            assert session.scalar(text("SELECT value FROM mutation_counter WHERE id = 1")) == 1
            assert promotion_cli._load_receipt(session, "committed") == payload
            session.rollback()
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
