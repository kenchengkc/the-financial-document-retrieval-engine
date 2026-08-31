"""Fail-closed cross-source adjudication of historical membership interval boundaries."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from fdre.research.historical_component_history import HistoricalComponentRecord
from fdre.research.historical_universe_evidence import MembershipEvidence
from fdre.research.historical_universe_lineage import TickerMembershipLineage

BoundaryKind = Literal["addition", "removal", "open_end"]
IntervalAdjudicationStatus = Literal[
    "verified",
    "provisional_boundary",
    "provisional_identity",
    "provisional_boundary_and_identity",
]

BOUNDARY_ADJUDICATION_SCHEMA_VERSION = "fdre-hu2-boundary-adjudication-v1"


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _symbol(value: str) -> str:
    return value.strip().upper().replace(".", "-")


@dataclass(frozen=True, slots=True)
class BoundaryAdjudication:
    kind: BoundaryKind
    effective_at: date | None
    source_marked_approximate: bool
    matching_sources: tuple[str, ...]
    required_independent_sources: int
    verified: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "effective_at": self.effective_at.isoformat() if self.effective_at else None,
            "source_marked_approximate": self.source_marked_approximate,
            "matching_sources": list(self.matching_sources),
            "required_independent_sources": self.required_independent_sources,
            "verified": self.verified,
        }


@dataclass(frozen=True, slots=True)
class IntervalAdjudication:
    record_id: str
    symbol: str
    cik: str
    effective_from: date
    effective_to: date | None
    source_valid_from: date
    start: BoundaryAdjudication
    end: BoundaryAdjudication
    membership_boundaries_verified: bool
    point_in_time_symbol_valid: bool
    status: IntervalAdjudicationStatus
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "symbol": self.symbol,
            "cik": self.cik,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "source_valid_from": self.source_valid_from.isoformat(),
            "start": self.start.as_dict(),
            "end": self.end.as_dict(),
            "membership_boundaries_verified": self.membership_boundaries_verified,
            "point_in_time_symbol_valid": self.point_in_time_symbol_valid,
            "status": self.status,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class BoundaryAdjudicationAudit:
    intervals: tuple[IntervalAdjudication, ...]
    audit_id: str

    def summary(self, *, target_start: date = date(2010, 1, 1)) -> dict[str, object]:
        status_counts = Counter(interval.status for interval in self.intervals)
        post_anchor = [
            interval for interval in self.intervals if interval.effective_from >= target_start
        ]
        post_status_counts = Counter(interval.status for interval in post_anchor)
        # Production readiness means every boundary has a deterministic decision and the
        # materializer can preserve unresolved rows as provisional.  It does not relabel those
        # rows verified: strict snapshots continue to fail closed whenever one is active.
        post_anchor_ready = bool(post_anchor) and all(
            interval.status
            in {
                "verified",
                "provisional_boundary",
                "provisional_identity",
                "provisional_boundary_and_identity",
            }
            for interval in post_anchor
        )
        return {
            "schema_version": BOUNDARY_ADJUDICATION_SCHEMA_VERSION,
            "audit_id": self.audit_id,
            "interval_count": len(self.intervals),
            "membership_boundaries_verified_count": sum(
                interval.membership_boundaries_verified for interval in self.intervals
            ),
            "point_in_time_symbol_valid_count": sum(
                interval.point_in_time_symbol_valid for interval in self.intervals
            ),
            "strict_materializable_verified_count": status_counts["verified"],
            "status_counts": dict(sorted(status_counts.items())),
            "post_anchor_start": target_start.isoformat(),
            "post_anchor_interval_count": len(post_anchor),
            "post_anchor_membership_boundaries_verified_count": sum(
                interval.membership_boundaries_verified for interval in post_anchor
            ),
            "post_anchor_strict_materializable_verified_count": post_status_counts[
                "verified"
            ],
            "post_anchor_status_counts": dict(sorted(post_status_counts.items())),
            "post_anchor_production_ready": post_anchor_ready,
            "post_anchor_unresolved_retained_provisional_count": sum(
                interval.status != "verified" for interval in post_anchor
            ),
        }


class BoundaryEvidenceIndex:
    """Index exact symbol/date claims from sources independent of the component row."""

    def __init__(
        self,
        *,
        evidence: Sequence[MembershipEvidence],
        lineages: Sequence[TickerMembershipLineage],
    ) -> None:
        sources: dict[tuple[str, str, date], set[str]] = defaultdict(set)
        open_lineages: dict[tuple[str, date], set[str]] = defaultdict(set)
        for record in evidence:
            sources[
                (_symbol(record.raw_symbol), record.event_type, record.effective_at)
            ].add(record.source.strip())
        for lineage in lineages:
            sources[(lineage.symbol, "addition", lineage.effective_from)].add(
                lineage.source
            )
            if lineage.effective_to is None:
                open_lineages[(lineage.symbol, lineage.effective_from)].add(lineage.source)
            else:
                sources[(lineage.symbol, "removal", lineage.effective_to)].add(
                    lineage.source
                )
        self._sources = {
            key: tuple(sorted(values)) for key, values in sources.items()
        }
        self._open_lineages = {
            key: tuple(sorted(values)) for key, values in open_lineages.items()
        }

    @staticmethod
    def _decision(
        *,
        kind: BoundaryKind,
        effective_at: date | None,
        approximate: bool,
        sources: tuple[str, ...],
    ) -> BoundaryAdjudication:
        # An exact lawcal date plus one exact external observation is two-source
        # corroboration.  A lawcal date explicitly marked approximate needs two external
        # sources to adjudicate the exact day rather than merely repeat the approximation.
        required = 2 if approximate else 1
        return BoundaryAdjudication(
            kind=kind,
            effective_at=effective_at,
            source_marked_approximate=approximate,
            matching_sources=sources,
            required_independent_sources=required,
            verified=len(sources) >= required,
        )

    def adjudicate(self, record: HistoricalComponentRecord) -> IntervalAdjudication:
        symbol = _symbol(record.symbol)
        start_sources = self._sources.get(
            (symbol, "addition", record.effective_from), ()
        )
        start = self._decision(
            kind="addition",
            effective_at=record.effective_from,
            approximate=record.added_approximate,
            sources=start_sources,
        )
        if record.effective_to is None:
            end_sources = self._open_lineages.get((symbol, record.effective_from), ())
            end = self._decision(
                kind="open_end",
                effective_at=None,
                approximate=False,
                sources=end_sources,
            )
        else:
            end_sources = self._sources.get(
                (symbol, "removal", record.effective_to), ()
            )
            end = self._decision(
                kind="removal",
                effective_at=record.effective_to,
                approximate=record.removed_approximate,
                sources=end_sources,
            )

        boundaries_verified = start.verified and end.verified
        # ``created_at`` is the date lawcal first serialized the row, not necessarily the date
        # the ticker became valid.  Never back-project a later terminal symbol on that field
        # alone, but accept the historical ticker when an independent source observes the same
        # symbol on the exact addition boundary.
        identity_valid = (
            record.source_valid_from == record.effective_from or start.verified
        )
        reasons: list[str] = []
        if not start.verified:
            reasons.append("addition_boundary_lacks_required_exact_external_support")
        if not end.verified:
            reasons.append(
                "open_status_lacks_exact_external_lineage_support"
                if record.effective_to is None
                else "removal_boundary_lacks_required_exact_external_support"
            )
        if not identity_valid:
            reasons.append("symbol_start_lacks_exact_external_identity_support")

        if boundaries_verified and identity_valid:
            status: IntervalAdjudicationStatus = "verified"
        elif boundaries_verified:
            status = "provisional_identity"
        elif identity_valid:
            status = "provisional_boundary"
        else:
            status = "provisional_boundary_and_identity"
        return IntervalAdjudication(
            record_id=record.record_id,
            symbol=symbol,
            cik=record.cik,
            effective_from=record.effective_from,
            effective_to=record.effective_to,
            source_valid_from=record.source_valid_from,
            start=start,
            end=end,
            membership_boundaries_verified=boundaries_verified,
            point_in_time_symbol_valid=identity_valid,
            status=status,
            reasons=tuple(reasons),
        )

    def audit(
        self,
        records: Sequence[HistoricalComponentRecord],
    ) -> BoundaryAdjudicationAudit:
        intervals = tuple(
            sorted(
                (self.adjudicate(record) for record in records),
                key=lambda item: (item.symbol, item.effective_from, item.cik, item.record_id),
            )
        )
        payload = {
            "schema_version": BOUNDARY_ADJUDICATION_SCHEMA_VERSION,
            "intervals": [interval.as_dict() for interval in intervals],
        }
        return BoundaryAdjudicationAudit(intervals=intervals, audit_id=_hash(payload))
