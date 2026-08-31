"""Pinned historical S&P component identity evidence with explicit CIKs.

The source adapter intentionally treats ticker history as identifier evidence, not as a fuzzy
company-name matcher. A ticker may resolve globally only when the complete pinned source maps it
to one CIK. Reused tickers require a unique dated interval match.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from fdre.research.historical_universe_evidence import MembershipEvidence
from fdre.research.historical_universe_identity import normalize_cik

ComponentIdentityStatus = Literal["resolved", "ambiguous", "unresolved"]
ComponentIdentityMethod = Literal[
    "unique_symbol_history",
    "dated_symbol_history",
    "unresolved",
]

_SOURCE = "lawcal/sp500-components-history"
_SCHEMA_VERSION = "fdre-hu2-historical-component-identity-v1"


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_symbol(value: str) -> str:
    normalized = value.strip().upper().replace("-", ".")
    # A small number of upstream change rows carry a trailing table delimiter. Removing the
    # delimiter is syntax cleanup, not an identifier similarity rule.
    return normalized.removesuffix("|").strip()


def _parse_source_date(value: str) -> tuple[date | None, bool]:
    raw = value.strip()
    if not raw:
        return None, False
    approximate = raw.endswith("*")
    if approximate:
        raw = raw[:-1]
    return date.fromisoformat(raw), approximate


@dataclass(frozen=True, slots=True)
class HistoricalComponentRecord:
    symbol: str
    cik: str
    name: str
    sector: str | None
    effective_from: date
    effective_to: date | None
    created_at: date
    added_approximate: bool
    removed_approximate: bool
    source_ref: str
    source_hash: str

    @property
    def source_valid_from(self) -> date:
        """First date the upstream source permits this symbol row to be replayed.

        ``lawcal/sp500-components-history`` records a new ``created_at`` value when a
        symbol is first observed.  Its own point-in-time helper requires both the
        membership interval and ``as_of >= created_at``.  Treating ``date_added`` as
        sufficient silently projects later ticker identities into the past.
        """

        return max(self.effective_from, self.created_at)

    @property
    def record_id(self) -> str:
        return _sha256_json(
            {
                "schema_version": _SCHEMA_VERSION,
                "symbol": self.symbol,
                "cik": self.cik,
                "effective_from": self.effective_from.isoformat(),
                "effective_to": self.effective_to.isoformat() if self.effective_to else None,
                "source_ref": self.source_ref,
                "source_hash": self.source_hash,
            }
        )


@dataclass(frozen=True, slots=True)
class ComponentIdentityResolution:
    evidence_id: str
    status: ComponentIdentityStatus
    method: ComponentIdentityMethod
    cik: str | None
    candidate_ciks: tuple[str, ...]
    source_record_ids: tuple[str, ...]
    resolution_hash: str
    reason: str | None = None


class HistoricalComponentHistoryAdapter:
    source_name = _SOURCE

    def __init__(self, *, source_ref: str) -> None:
        if not source_ref.strip():
            raise ValueError("source_ref is required")
        self.source_ref = source_ref.strip()

    def load(self, path: Path) -> tuple[HistoricalComponentRecord, ...]:
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        rows: list[HistoricalComponentRecord] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {
                "symbol",
                "cik",
                "name",
                "sector",
                "date_added",
                "date_removed",
                "created_at",
            }
            if not required.issubset(reader.fieldnames or ()):
                raise ValueError("historical component CSV is missing required columns")
            for row_number, row in enumerate(reader, start=2):
                symbol = normalize_symbol(row["symbol"] or "")
                raw_cik = (row["cik"] or "").strip()
                name = (row["name"] or "").strip()
                effective_from, added_approximate = _parse_source_date(
                    row["date_added"] or ""
                )
                effective_to, removed_approximate = _parse_source_date(
                    row["date_removed"] or ""
                )
                created_at, _ = _parse_source_date(row["created_at"] or "")
                if not symbol or not raw_cik or not name:
                    raise ValueError(f"invalid historical component row {row_number}")
                if effective_from is None or created_at is None:
                    raise ValueError(f"invalid historical component row {row_number}")
                if effective_to is not None and effective_to <= effective_from:
                    raise ValueError(
                        "non-positive historical component interval "
                        f"on row {row_number}"
                    )
                rows.append(
                    HistoricalComponentRecord(
                        symbol=symbol,
                        cik=normalize_cik(raw_cik),
                        name=name,
                        sector=(row["sector"] or "").strip() or None,
                        effective_from=effective_from,
                        effective_to=effective_to,
                        created_at=created_at,
                        added_approximate=added_approximate,
                        removed_approximate=removed_approximate,
                        source_ref=self.source_ref,
                        source_hash=source_hash,
                    )
                )
        rows.sort(key=lambda item: (item.symbol, item.effective_from, item.cik, item.record_id))
        return tuple(rows)


class HistoricalComponentIdentityIndex:
    def __init__(self, records: Sequence[HistoricalComponentRecord]) -> None:
        by_symbol: dict[str, list[HistoricalComponentRecord]] = defaultdict(list)
        for record in records:
            by_symbol[record.symbol].append(record)
        self._by_symbol = {
            symbol: tuple(sorted(items, key=lambda item: (item.effective_from, item.record_id)))
            for symbol, items in by_symbol.items()
        }

    def records_for_symbol(self, symbol: str) -> tuple[HistoricalComponentRecord, ...]:
        return self._by_symbol.get(normalize_symbol(symbol), ())

    @property
    def symbol_count(self) -> int:
        return len(self._by_symbol)


def _dated_candidates(
    evidence: MembershipEvidence,
    records: Sequence[HistoricalComponentRecord],
) -> tuple[HistoricalComponentRecord, ...]:
    when = evidence.effective_at
    matches: list[HistoricalComponentRecord] = []
    for record in records:
        if evidence.event_type == "removal":
            active = record.effective_from < when and (
                record.effective_to is None or when <= record.effective_to
            )
        else:
            active = record.effective_from <= when and (
                record.effective_to is None or when < record.effective_to
            )
        if active:
            matches.append(record)
    return tuple(matches)


def resolve_component_identity(
    evidence: MembershipEvidence,
    index: HistoricalComponentIdentityIndex,
) -> ComponentIdentityResolution:
    records = index.records_for_symbol(evidence.raw_symbol)
    all_ciks = tuple(sorted({record.cik for record in records}))
    method: ComponentIdentityMethod = "unresolved"
    candidate_records: tuple[HistoricalComponentRecord, ...] = ()
    candidate_ciks: tuple[str, ...] = ()

    if len(all_ciks) == 1:
        method = "unique_symbol_history"
        candidate_records = records
        candidate_ciks = all_ciks
    elif len(all_ciks) > 1:
        candidate_records = _dated_candidates(evidence, records)
        candidate_ciks = tuple(sorted({record.cik for record in candidate_records}))
        if len(candidate_ciks) == 1:
            method = "dated_symbol_history"

    if len(candidate_ciks) == 1:
        status: ComponentIdentityStatus = "resolved"
        cik = candidate_ciks[0]
        reason = None
    elif len(candidate_ciks) > 1:
        status = "ambiguous"
        cik = None
        reason = "historical ticker maps to multiple CIKs at the evidence date"
    else:
        status = "unresolved"
        cik = None
        reason = (
            "historical ticker is absent from the pinned component identity source"
            if not records
            else "reused historical ticker could not be dated to one CIK"
        )

    source_record_ids = tuple(sorted(record.record_id for record in candidate_records))
    resolution_hash = _sha256_json(
        {
            "schema_version": _SCHEMA_VERSION,
            "evidence_id": evidence.evidence_id,
            "method": method,
            "status": status,
            "candidate_ciks": list(candidate_ciks),
            "source_record_ids": list(source_record_ids),
        }
    )
    return ComponentIdentityResolution(
        evidence_id=evidence.evidence_id,
        status=status,
        method=method,
        cik=cik,
        candidate_ciks=candidate_ciks,
        source_record_ids=source_record_ids,
        resolution_hash=resolution_hash,
        reason=reason,
    )
