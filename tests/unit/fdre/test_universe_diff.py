from __future__ import annotations

from datetime import date
from typing import cast

import pytest

from fdre.research.historical_universe import UniverseSnapshot, UniverseSnapshotConstituent
from fdre.universe_diff import compare_universe_snapshots, universe_diff_to_dict


def test_universe_diff_separates_membership_changes_from_identity_changes() -> None:
    before = UniverseSnapshot(
        universe_code="sp500",
        as_of=date(2020, 1, 2),
        snapshot_id="before-snapshot",
        includes_provisional=False,
        constituents=(
            _constituent(1, "AAA", identity_source_hash="identity-a"),
            _constituent(2, "BBB", identity_source_hash="identity-b"),
        ),
    )
    after = UniverseSnapshot(
        universe_code="sp500",
        as_of=date(2021, 1, 4),
        snapshot_id="after-snapshot",
        includes_provisional=False,
        constituents=(
            _constituent(
                1,
                "AAB",
                identity_effective_from=date(2020, 6, 1),
                identity_source_hash="identity-a-renamed",
            ),
            _constituent(3, "CCC", identity_source_hash="identity-c"),
        ),
    )

    diff = compare_universe_snapshots(before, after)
    assert diff.from_snapshot_id == "before-snapshot"
    assert diff.to_snapshot_id == "after-snapshot"
    assert [row.security_id for row in diff.added] == [3]
    assert [row.security_id for row in diff.removed] == [2]
    assert len(diff.changed) == 1
    assert diff.changed[0].security_id == 1
    assert diff.changed[0].before.symbol == "AAA"
    assert diff.changed[0].after.symbol == "AAB"
    assert diff.changed[0].changed_fields == (
        "symbol",
        "identity_effective_from",
        "identity_source_hash",
    )

    payload = universe_diff_to_dict(diff)
    summary = cast(dict[str, int], payload["summary"])
    assert summary == {
        "from_count": 2,
        "to_count": 2,
        "added_count": 1,
        "removed_count": 1,
        "changed_count": 1,
        "retained_count": 1,
    }


def test_universe_diff_rejects_incomparable_snapshots() -> None:
    base = UniverseSnapshot(
        universe_code="sp500",
        as_of=date(2021, 1, 4),
        snapshot_id="base",
        includes_provisional=False,
        constituents=(),
    )
    with pytest.raises(ValueError, match="same universe_code"):
        compare_universe_snapshots(
            base,
            UniverseSnapshot(
                universe_code="nasdaq100",
                as_of=date(2021, 2, 1),
                snapshot_id="other",
                includes_provisional=False,
                constituents=(),
            ),
        )
    with pytest.raises(ValueError, match="same provisional-evidence mode"):
        compare_universe_snapshots(
            base,
            UniverseSnapshot(
                universe_code="sp500",
                as_of=date(2021, 2, 1),
                snapshot_id="other",
                includes_provisional=True,
                constituents=(),
            ),
        )
    with pytest.raises(ValueError, match="must not precede"):
        compare_universe_snapshots(
            base,
            UniverseSnapshot(
                universe_code="sp500",
                as_of=date(2020, 12, 31),
                snapshot_id="older",
                includes_provisional=False,
                constituents=(),
            ),
        )


def _constituent(
    security_id: int,
    symbol: str,
    *,
    identity_effective_from: date = date(2019, 1, 1),
    identity_source_hash: str,
) -> UniverseSnapshotConstituent:
    return UniverseSnapshotConstituent(
        security_id=security_id,
        cik=f"{security_id:010d}",
        symbol=symbol,
        name=f"Company {symbol}",
        exchange="NYSE",
        membership_effective_from=date(2019, 1, 1),
        identity_effective_from=identity_effective_from,
        membership_source_hash=f"membership-{security_id}",
        identity_source_hash=identity_source_hash,
        verification_status="verified",
    )
