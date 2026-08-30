"""Independent complete-snapshot anchors for Historical Universe HU-2.

The initial anchor adapter targets the public fja05680/sp500 historical component file. That
source encodes ticker-reuse lineage with terminal ``-YYYYMM`` suffixes. Those lineage tokens are
preserved as source identity; a separate display symbol is exposed for comparison only.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

_LINEAGE_SUFFIX = re.compile(r"^(?P<symbol>.+)-(?P<end_yyyymm>\d{6})$")
_ANCHOR_SCHEMA_VERSION = "fdre-hu2-complete-snapshot-anchor-v1"


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_display_symbol(value: str) -> str:
    """Normalize a source ticker for display without discarding lineage identity."""

    token = value.strip().upper()
    match = _LINEAGE_SUFFIX.fullmatch(token)
    if match is not None:
        token = match.group("symbol")
    return token.replace(".", "-")


@dataclass(frozen=True, slots=True)
class CompleteSnapshotConstituent:
    lineage_token: str
    display_symbol: str
    lineage_end_yyyymm: str | None


@dataclass(frozen=True, slots=True)
class CompleteUniverseSnapshotAnchor:
    universe_code: str
    effective_at: date
    constituents: tuple[CompleteSnapshotConstituent, ...]
    source: str
    source_url: str
    source_ref: str
    source_observed_at: datetime
    source_hash: str

    @property
    def constituent_count(self) -> int:
        return len(self.constituents)

    @property
    def duplicate_display_symbols(self) -> tuple[str, ...]:
        counts: dict[str, int] = {}
        for item in self.constituents:
            counts[item.display_symbol] = counts.get(item.display_symbol, 0) + 1
        return tuple(sorted(symbol for symbol, count in counts.items() if count > 1))

    @property
    def anchor_id(self) -> str:
        return _sha256_json(
            {
                "schema_version": _ANCHOR_SCHEMA_VERSION,
                "universe_code": self.universe_code,
                "effective_at": self.effective_at.isoformat(),
                "lineage_tokens": [item.lineage_token for item in self.constituents],
                "source": self.source,
                "source_ref": self.source_ref,
                "source_hash": self.source_hash,
            }
        )


class HistoricalComponentsSnapshotAdapter:
    """Read one complete point-in-time snapshot from the fja05680/sp500 CSV."""

    source_name = "fja05680/sp500-historical-components"

    def __init__(self, *, source_ref: str, source_url: str) -> None:
        if not source_ref.strip():
            raise ValueError("source_ref is required for a pinned anchor")
        if not source_url.strip():
            raise ValueError("source_url is required")
        self.source_ref = source_ref.strip()
        self.source_url = source_url.strip()

    @staticmethod
    def _constituent(raw_token: str) -> CompleteSnapshotConstituent:
        lineage_token = raw_token.strip().upper()
        if not lineage_token:
            raise ValueError("empty constituent token in complete snapshot")
        match = _LINEAGE_SUFFIX.fullmatch(lineage_token)
        return CompleteSnapshotConstituent(
            lineage_token=lineage_token,
            display_symbol=normalize_display_symbol(lineage_token),
            lineage_end_yyyymm=(match.group("end_yyyymm") if match is not None else None),
        )

    def load_latest_on_or_before(
        self,
        path: Path,
        *,
        target_date: date,
        observed_at: datetime,
        universe_code: str = "sp500",
    ) -> CompleteUniverseSnapshotAnchor:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")

        source_bytes = path.read_bytes()
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        rows: list[tuple[date, str]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or not {"date", "tickers"}.issubset(reader.fieldnames):
                raise ValueError("historical snapshot CSV must contain date,tickers columns")
            for row in reader:
                raw_date = (row.get("date") or "").strip()
                raw_tickers = (row.get("tickers") or "").strip()
                if not raw_date or not raw_tickers:
                    continue
                effective_at = date.fromisoformat(raw_date)
                if effective_at <= target_date:
                    rows.append((effective_at, raw_tickers))
        if not rows:
            raise ValueError(f"no complete snapshot exists on or before {target_date.isoformat()}")

        effective_at, raw_tickers = max(rows, key=lambda item: item[0])
        constituents = tuple(
            sorted(
                (self._constituent(token) for token in raw_tickers.split(",")),
                key=lambda item: item.lineage_token,
            )
        )
        lineage_tokens = [item.lineage_token for item in constituents]
        if len(lineage_tokens) != len(set(lineage_tokens)):
            raise ValueError("complete snapshot contains duplicate lineage tokens")
        if not 490 <= len(constituents) <= 510:
            raise ValueError(
                "complete S&P 500 snapshot has implausible constituent count: "
                f"{len(constituents)}"
            )

        return CompleteUniverseSnapshotAnchor(
            universe_code=universe_code.strip().lower(),
            effective_at=effective_at,
            constituents=constituents,
            source=self.source_name,
            source_url=self.source_url,
            source_ref=self.source_ref,
            source_observed_at=observed_at,
            source_hash=source_hash,
        )
