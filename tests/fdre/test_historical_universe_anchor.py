from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from fdre.research.historical_universe_anchor import (
    HistoricalComponentsSnapshotAdapter,
    normalize_display_symbol,
)

OBSERVED_AT = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def _write_history(path: Path) -> None:
    first = [f"T{i:03d}" for i in range(500)]
    second = list(first)
    second[0] = "XL-201809"
    second[1] = "XL"
    path.write_text(
        "date,tickers\n"
        f'2009-12-24,"{",".join(first)}"\n'
        f'2009-12-30,"{",".join(second)}"\n'
        f'2010-01-06,"{",".join(first)}"\n',
        encoding="utf-8",
    )


def test_display_symbol_preserves_lineage_token_separately() -> None:
    assert normalize_display_symbol("XL-201809") == "XL"
    assert normalize_display_symbol("BF.B") == "BF-B"


def test_anchor_selects_latest_complete_snapshot_on_or_before_target(tmp_path: Path) -> None:
    path = tmp_path / "history.csv"
    _write_history(path)
    adapter = HistoricalComponentsSnapshotAdapter(
        source_ref="c31ac3cc56f28cf9a02b4e694eff7ceab596a0ff",
        source_url="https://example.test/history.csv",
    )

    anchor = adapter.load_latest_on_or_before(
        path,
        target_date=date(2010, 1, 1),
        observed_at=OBSERVED_AT,
    )

    assert anchor.effective_at == date(2009, 12, 30)
    assert anchor.constituent_count == 500
    assert "XL" in anchor.duplicate_display_symbols
    lineage_tokens = {item.lineage_token for item in anchor.constituents}
    assert {"XL", "XL-201809"}.issubset(lineage_tokens)
    assert len(anchor.anchor_id) == 64


def test_anchor_rejects_incomplete_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "history.csv"
    path.write_text('date,tickers\n2009-12-30,"A,B,C"\n', encoding="utf-8")
    adapter = HistoricalComponentsSnapshotAdapter(
        source_ref="abc123",
        source_url="https://example.test/history.csv",
    )

    try:
        adapter.load_latest_on_or_before(
            path,
            target_date=date(2010, 1, 1),
            observed_at=OBSERVED_AT,
        )
    except ValueError as exc:
        assert "implausible constituent count" in str(exc)
    else:
        raise AssertionError("incomplete snapshot should fail closed")
