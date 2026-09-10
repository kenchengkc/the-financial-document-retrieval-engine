from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import cast

import pytest
import scripts.research.universe as universe_cli
from sqlalchemy.orm import Session

from fdre.research.historical_universe import UniverseSnapshot, UniverseSnapshotConstituent


def _snapshot(
    *,
    as_of: date,
    symbol: str,
    identity_hash: str,
) -> UniverseSnapshot:
    constituent = UniverseSnapshotConstituent(
        security_id=1,
        cik="0000000001",
        symbol=symbol,
        name="Example Corp",
        exchange="NYSE",
        membership_effective_from=date(2020, 1, 1),
        identity_effective_from=as_of,
        membership_source_hash="membership-source",
        identity_source_hash=identity_hash,
        verification_status="verified",
    )
    return UniverseSnapshot(
        universe_code="sp500",
        as_of=as_of,
        constituents=(constituent,),
        snapshot_id=("a" if symbol == "AAA" else "b") * 64,
        includes_provisional=False,
    )


def test_snapshot_command_exports_the_same_content_addressed_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(
        as_of=date(2024, 1, 2),
        symbol="AAA",
        identity_hash="identity-a",
    )
    output = tmp_path / "snapshot.json"
    args = universe_cli._parser().parse_args(
        ["snapshot", "sp500", "--as-of", "2024-01-02", "--output", str(output)]
    )
    monkeypatch.setattr(universe_cli, "universe_from_session", lambda *args, **kwargs: snapshot)

    payload = universe_cli._snapshot_command(cast(Session, object()), args)

    assert payload["snapshot_id"] == snapshot.snapshot_id
    assert payload["constituent_count"] == 1
    assert json.loads(output.read_text()) == payload


def test_diff_command_treats_ticker_rename_as_stable_identity_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _snapshot(
        as_of=date(2024, 1, 2),
        symbol="AAA",
        identity_hash="identity-a",
    )
    after = _snapshot(
        as_of=date(2025, 1, 2),
        symbol="AAB",
        identity_hash="identity-b",
    )
    snapshots = iter((before, after))
    output = tmp_path / "diff.json"
    args = universe_cli._parser().parse_args(
        [
            "diff",
            "sp500",
            "--from",
            "2024-01-02",
            "--to",
            "2025-01-02",
            "--output",
            str(output),
        ]
    )
    monkeypatch.setattr(
        universe_cli,
        "universe_from_session",
        lambda *args, **kwargs: next(snapshots),
    )

    payload = universe_cli._diff_command(cast(Session, object()), args)

    summary = cast(dict[str, int], payload["summary"])
    assert summary == {
        "from_count": 1,
        "to_count": 1,
        "added_count": 0,
        "removed_count": 0,
        "changed_count": 1,
        "retained_count": 1,
    }
    changed = cast(list[dict[str, object]], payload["changed"])
    assert changed[0]["security_id"] == 1
    assert "symbol" in cast(list[str], changed[0]["changed_fields"])
    assert json.loads(output.read_text()) == payload


def test_parquet_snapshot_requires_an_output_path(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = _snapshot(
        as_of=date(2024, 1, 2),
        symbol="AAA",
        identity_hash="identity-a",
    )
    args = universe_cli._parser().parse_args(
        ["snapshot", "sp500", "--as-of", "2024-01-02", "--format", "parquet"]
    )
    monkeypatch.setattr(universe_cli, "universe_from_session", lambda *args, **kwargs: snapshot)

    with pytest.raises(ValueError, match="--output is required"):
        universe_cli._snapshot_command(cast(Session, object()), args)


def test_operational_commands_are_discoverable_from_one_surface() -> None:
    help_text = universe_cli._parser().format_help()

    for command in ("snapshot", "diff", "audit", "reconcile", "validate", "promote"):
        assert command in help_text


def test_operational_delegation_preserves_arguments_exit_code_and_sys_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_argv = sys.argv
    observed: list[str] = []

    def delegated_main() -> int:
        observed.extend(sys.argv[1:])
        return 2

    monkeypatch.setattr(
        universe_cli,
        "_operation_entrypoint",
        lambda command: delegated_main,
    )

    result = universe_cli.main(["validate", "--require-pass", "--output", "gate.json"])

    assert result == 2
    assert observed == ["--require-pass", "--output", "gate.json"]
    assert sys.argv is original_argv
