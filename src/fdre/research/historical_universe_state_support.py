"""Plan exact state corroboration for provisional Historical Universe rows.

This module never guesses an addition/removal boundary. It asks a narrower question: does a
pinned independent complete-history ticker interval assert the same index-membership state for
every day covered by an already-materialized provisional interval? Only membership rows can be
promoted from this evidence. Ticker-only history is deliberately insufficient to prove that a
symbol belonged to a particular SEC issuer, so identity rows remain diagnostic-only even when a
same-symbol interval is fully contained.

Partial overlaps, one-day convention disagreements, reused-ticker ambiguity, and missing symbols
remain provisional.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

from fdre.research.historical_universe_lineage import (
    TickerMembershipLineage,
    normalize_symbol,
)

STATE_SUPPORT_SCHEMA_VERSION = "fdre-hu-state-support-v2"
StateRowKind = Literal["membership", "identity"]
StateSupportStatus = Literal["fully_supported", "partial", "unsupported", "ambiguous"]


@dataclass(frozen=True, slots=True)
class ProvisionalStateInterval:
    row_kind: StateRowKind
    row_id: int
    security_id: int
    cik: str
    symbol: str
    effective_from: date
    effective_to: date | None
    source: str
    source_hash: str


@dataclass(frozen=True, slots=True)
class StateSupportDecision:
    row_kind: StateRowKind
    row_id: int
    security_id: int
    cik: str
    symbol: str
    effective_from: date
    effective_to: date | None
    source_hash: str
    status: StateSupportStatus
    lineage_id: str | None
    lineage_effective_from: date | None
    lineage_effective_to: date | None
    lineage_source: str | None
    lineage_source_ref: str | None
    lineage_source_hash: str | None
    reason: str
    decision_hash: str

    @property
    def promotable(self) -> bool:
        """Ticker-only state evidence may promote membership, never issuer identity."""
        return self.row_kind == "membership" and self.status == "fully_supported"

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["effective_from"] = self.effective_from.isoformat()
        payload["effective_to"] = self.effective_to.isoformat() if self.effective_to else None
        payload["lineage_effective_from"] = (
            self.lineage_effective_from.isoformat() if self.lineage_effective_from else None
        )
        payload["lineage_effective_to"] = (
            self.lineage_effective_to.isoformat() if self.lineage_effective_to else None
        )
        payload["promotable"] = self.promotable
        return payload


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _contains(lineage: TickerMembershipLineage, interval: ProvisionalStateInterval) -> bool:
    if lineage.effective_from > interval.effective_from:
        return False
    if interval.effective_to is None:
        return lineage.effective_to is None
    return lineage.effective_to is None or interval.effective_to <= lineage.effective_to


def _overlaps(lineage: TickerMembershipLineage, interval: ProvisionalStateInterval) -> bool:
    if lineage.effective_to is not None and lineage.effective_to <= interval.effective_from:
        return False
    return interval.effective_to is None or interval.effective_to > lineage.effective_from


def plan_state_support(
    intervals: tuple[ProvisionalStateInterval, ...],
    lineages: tuple[TickerMembershipLineage, ...],
) -> tuple[StateSupportDecision, ...]:
    """Return deterministic, fail-closed state-support decisions for provisional rows."""
    by_symbol: dict[str, list[TickerMembershipLineage]] = {}
    for lineage in lineages:
        by_symbol.setdefault(lineage.symbol, []).append(lineage)
    for values in by_symbol.values():
        values.sort(
            key=lambda item: (
                item.effective_from,
                item.effective_to or date.max,
                item.lineage_id,
            )
        )

    decisions: list[StateSupportDecision] = []
    seen_keys: set[tuple[StateRowKind, int]] = set()
    ordered = sorted(
        intervals,
        key=lambda item: (
            item.row_kind,
            item.effective_from,
            item.security_id,
            item.row_id,
        ),
    )
    for interval in ordered:
        key = (interval.row_kind, interval.row_id)
        if key in seen_keys:
            raise ValueError(
                f"duplicate provisional state row: {interval.row_kind}/{interval.row_id}"
            )
        seen_keys.add(key)
        symbol = normalize_symbol(interval.symbol)
        candidates = tuple(by_symbol.get(symbol, ()))
        containing = tuple(item for item in candidates if _contains(item, interval))
        overlapping = tuple(item for item in candidates if _overlaps(item, interval))
        if len(containing) == 1:
            status: StateSupportStatus = "fully_supported"
            lineage = containing[0]
            if interval.row_kind == "membership":
                reason = (
                    "one pinned independent complete-history ticker interval fully contains the "
                    "materialized provisional membership interval"
                )
            else:
                reason = (
                    "same-symbol ticker state is fully contained, but ticker-only evidence does "
                    "not bind the symbol to this SEC issuer; identity remains diagnostic-only"
                )
        elif len(containing) > 1:
            status = "ambiguous"
            lineage = None
            reason = "multiple pinned ticker intervals fully contain the provisional interval"
        elif overlapping:
            status = "partial"
            lineage = None
            reason = (
                "pinned ticker history overlaps but does not fully contain the provisional "
                "interval; boundary/date-convention disagreement remains unresolved"
            )
        else:
            status = "unsupported"
            lineage = None
            reason = "no pinned ticker-history interval overlaps the provisional interval"

        decision_payload = {
            "schema_version": STATE_SUPPORT_SCHEMA_VERSION,
            "row_kind": interval.row_kind,
            "row_id": interval.row_id,
            "security_id": interval.security_id,
            "cik": interval.cik,
            "symbol": symbol,
            "effective_from": interval.effective_from.isoformat(),
            "effective_to": interval.effective_to.isoformat() if interval.effective_to else None,
            "source_hash": interval.source_hash,
            "status": status,
            "lineage_id": lineage.lineage_id if lineage is not None else None,
            "lineage_source_hash": lineage.source_hash if lineage is not None else None,
            "reason": reason,
        }
        decisions.append(
            StateSupportDecision(
                row_kind=interval.row_kind,
                row_id=interval.row_id,
                security_id=interval.security_id,
                cik=interval.cik,
                symbol=symbol,
                effective_from=interval.effective_from,
                effective_to=interval.effective_to,
                source_hash=interval.source_hash,
                status=status,
                lineage_id=lineage.lineage_id if lineage is not None else None,
                lineage_effective_from=(
                    lineage.effective_from if lineage is not None else None
                ),
                lineage_effective_to=lineage.effective_to if lineage is not None else None,
                lineage_source=lineage.source if lineage is not None else None,
                lineage_source_ref=lineage.source_ref if lineage is not None else None,
                lineage_source_hash=lineage.source_hash if lineage is not None else None,
                reason=reason,
                decision_hash=_digest(decision_payload),
            )
        )
    return tuple(decisions)


def corroborated_source(source: str) -> str:
    suffix = "+fja05680/sp500-state-corroboration"
    return source if source.endswith(suffix) else source + suffix


def corroborated_source_hash(decision: StateSupportDecision, *, plan_id: str) -> str:
    if (
        not decision.promotable
        or decision.lineage_id is None
        or decision.lineage_source_hash is None
    ):
        raise ValueError("only fully supported membership decisions have corroborated provenance")
    return _digest(
        {
            "schema_version": STATE_SUPPORT_SCHEMA_VERSION,
            "plan_id": plan_id,
            "decision_hash": decision.decision_hash,
            "prior_source_hash": decision.source_hash,
            "lineage_id": decision.lineage_id,
            "lineage_source_hash": decision.lineage_source_hash,
        }
    )


def state_support_plan_id(decisions: tuple[StateSupportDecision, ...]) -> str:
    return _digest(
        {
            "schema_version": STATE_SUPPORT_SCHEMA_VERSION,
            "decision_hashes": [item.decision_hash for item in decisions],
        }
    )
