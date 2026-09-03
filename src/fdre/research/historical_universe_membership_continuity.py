"""Conservative continuity adjudication for HU-5 provisional memberships.

The planner intentionally resolves only two high-confidence shapes:

* a live/open membership whose exact CIK+current symbol is present in a pinned current
  constituent snapshot with a date-added no later than the provisional interval start; and
* a provisional interval that is wholly covered by exactly one already-verified sibling
  membership for the same issuer, which identifies a duplicate ticker/security split rather
  than an independent constituent.

Everything else stays unresolved for narrower historical-event adjudication.  In particular,
sharing a CIK is never sufficient to collapse simultaneous share classes.
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

from fdre.research.historical_universe_lineage import normalize_symbol
from fdre.research.historical_universe_strict_coverage import ProvisionalMembershipBlocker

ContinuityAction = Literal["verify", "reject", "unresolved"]
ContinuityMethod = Literal[
    "current_constituent_anchor",
    "single_verified_sibling_cover",
    "unresolved",
]

MEMBERSHIP_CONTINUITY_SCHEMA_VERSION = "fdre-hu5-membership-continuity-v1"


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_cik(value: str) -> str:
    stripped = value.strip()
    return stripped.zfill(10) if stripped.isdigit() else stripped


@dataclass(frozen=True, slots=True)
class CurrentConstituentAnchor:
    symbol: str
    cik: str
    date_added: date
    source_ref: str
    source_hash: str
    row_hash: str

    @property
    def evidence_id(self) -> str:
        return _hash(
            {
                "schema_version": MEMBERSHIP_CONTINUITY_SCHEMA_VERSION,
                "kind": "current_constituent_anchor",
                "symbol": self.symbol,
                "cik": self.cik,
                "date_added": self.date_added.isoformat(),
                "source_ref": self.source_ref,
                "source_hash": self.source_hash,
                "row_hash": self.row_hash,
            }
        )


class CurrentConstituentAnchorAdapter:
    """Parse pinned ``fja05680/sp500`` current constituent rows."""

    source = "fja05680/sp500-current-constituents"

    def __init__(self, *, source_ref: str) -> None:
        if not source_ref.strip():
            raise ValueError("source_ref is required")
        self.source_ref = source_ref.strip()

    def load(self, path: Path) -> tuple[CurrentConstituentAnchor, ...]:
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        anchors: list[CurrentConstituentAnchor] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"Symbol", "Date added", "CIK"}
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                raise ValueError("current constituent CSV must contain Symbol,Date added,CIK")
            for row_number, row in enumerate(reader, start=2):
                raw_symbol = (row.get("Symbol") or "").strip()
                raw_cik = (row.get("CIK") or "").strip()
                raw_date = (row.get("Date added") or "").strip()
                if not raw_symbol or not raw_cik or not raw_date:
                    continue
                try:
                    added = date.fromisoformat(raw_date)
                except ValueError as exc:
                    raise ValueError(
                        f"invalid Date added on current constituent row {row_number}: {raw_date!r}"
                    ) from exc
                canonical_row = {
                    "symbol": raw_symbol,
                    "cik": raw_cik,
                    "date_added": raw_date,
                }
                anchors.append(
                    CurrentConstituentAnchor(
                        symbol=normalize_symbol(raw_symbol),
                        cik=normalize_cik(raw_cik),
                        date_added=added,
                        source_ref=self.source_ref,
                        source_hash=source_hash,
                        row_hash=_hash(canonical_row),
                    )
                )
        anchors.sort(key=lambda item: (item.cik, item.symbol, item.date_added, item.evidence_id))
        return tuple(anchors)


@dataclass(frozen=True, slots=True)
class VerifiedSiblingMembership:
    membership_id: int
    security_id: int
    cik: str
    effective_from: date
    effective_to: date | None
    source_hash: str

    def covers(self, blocker: ProvisionalMembershipBlocker) -> bool:
        if normalize_cik(self.cik) != normalize_cik(blocker.cik):
            return False
        if self.security_id == blocker.security_id:
            return False
        if self.effective_from > blocker.effective_from:
            return False
        if blocker.effective_to is None:
            return self.effective_to is None
        return self.effective_to is None or self.effective_to >= blocker.effective_to

    @property
    def evidence_id(self) -> str:
        return _hash(
            {
                "schema_version": MEMBERSHIP_CONTINUITY_SCHEMA_VERSION,
                "kind": "verified_sibling_membership",
                "membership_id": self.membership_id,
                "security_id": self.security_id,
                "cik": normalize_cik(self.cik),
                "effective_from": self.effective_from.isoformat(),
                "effective_to": self.effective_to.isoformat() if self.effective_to else None,
                "source_hash": self.source_hash,
            }
        )


@dataclass(frozen=True, slots=True)
class MembershipContinuityDecision:
    membership_id: int
    security_id: int
    cik: str
    effective_from: date
    effective_to: date | None
    prior_source_hash: str
    action: ContinuityAction
    method: ContinuityMethod
    evidence_ids: tuple[str, ...]
    reason: str
    decision_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "membership_id": self.membership_id,
            "security_id": self.security_id,
            "cik": self.cik,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "prior_source_hash": self.prior_source_hash,
            "action": self.action,
            "method": self.method,
            "evidence_ids": list(self.evidence_ids),
            "reason": self.reason,
            "decision_hash": self.decision_hash,
        }


def _active_open_symbols(blocker: ProvisionalMembershipBlocker) -> tuple[str, ...]:
    if blocker.effective_to is not None:
        return ()
    symbols = {
        normalize_symbol(identity.symbol)
        for identity in blocker.identities
        if identity.effective_to is None and identity.verification_status != "rejected"
    }
    return tuple(sorted(symbols))


def _decision(
    blocker: ProvisionalMembershipBlocker,
    *,
    action: ContinuityAction,
    method: ContinuityMethod,
    evidence_ids: Sequence[str],
    reason: str,
) -> MembershipContinuityDecision:
    normalized_evidence = tuple(sorted(set(evidence_ids)))
    payload = {
        "schema_version": MEMBERSHIP_CONTINUITY_SCHEMA_VERSION,
        "membership_id": blocker.membership_id,
        "security_id": blocker.security_id,
        "cik": normalize_cik(blocker.cik),
        "effective_from": blocker.effective_from.isoformat(),
        "effective_to": blocker.effective_to.isoformat() if blocker.effective_to else None,
        "prior_source_hash": blocker.source_hash,
        "action": action,
        "method": method,
        "evidence_ids": list(normalized_evidence),
        "reason": reason,
    }
    return MembershipContinuityDecision(
        membership_id=blocker.membership_id,
        security_id=blocker.security_id,
        cik=normalize_cik(blocker.cik),
        effective_from=blocker.effective_from,
        effective_to=blocker.effective_to,
        prior_source_hash=blocker.source_hash,
        action=action,
        method=method,
        evidence_ids=normalized_evidence,
        reason=reason,
        decision_hash=_hash(payload),
    )


def plan_membership_continuity(
    blockers: Sequence[ProvisionalMembershipBlocker],
    *,
    current_anchors: Sequence[CurrentConstituentAnchor],
    verified_siblings: Sequence[VerifiedSiblingMembership],
) -> tuple[MembershipContinuityDecision, ...]:
    """Plan only fail-closed current-anchor and unique-sibling continuity decisions."""
    blocker_ids = [item.membership_id for item in blockers]
    if len(set(blocker_ids)) != len(blocker_ids):
        raise ValueError("membership blocker IDs must be unique")

    anchors_by_cik_symbol: dict[tuple[str, str], list[CurrentConstituentAnchor]] = defaultdict(list)
    for anchor in current_anchors:
        anchors_by_cik_symbol[(anchor.cik, anchor.symbol)].append(anchor)
    siblings_by_cik: dict[str, list[VerifiedSiblingMembership]] = defaultdict(list)
    for sibling in verified_siblings:
        siblings_by_cik[normalize_cik(sibling.cik)].append(sibling)

    decisions: list[MembershipContinuityDecision] = []
    for blocker in sorted(blockers, key=lambda item: item.membership_id):
        cik = normalize_cik(blocker.cik)
        active_symbols = _active_open_symbols(blocker)
        current_matches = [
            anchor
            for symbol in active_symbols
            for anchor in anchors_by_cik_symbol.get((cik, symbol), ())
            if anchor.date_added <= blocker.effective_from
        ]
        unique_current = {anchor.evidence_id: anchor for anchor in current_matches}
        if blocker.effective_to is None and len(active_symbols) == 1 and len(unique_current) == 1:
            anchor = next(iter(unique_current.values()))
            decisions.append(
                _decision(
                    blocker,
                    action="verify",
                    method="current_constituent_anchor",
                    evidence_ids=(anchor.evidence_id,),
                    reason=(
                        "Pinned current constituent snapshot binds the exact active symbol and CIK "
                        "and states a membership date no later than this open interval start."
                    ),
                )
            )
            continue

        covering = [
            sibling
            for sibling in siblings_by_cik.get(cik, ())
            if sibling.covers(blocker)
        ]
        covering_security_ids = {item.security_id for item in covering}
        if len(covering) == 1 and len(covering_security_ids) == 1:
            sibling = covering[0]
            decisions.append(
                _decision(
                    blocker,
                    action="reject",
                    method="single_verified_sibling_cover",
                    evidence_ids=(sibling.evidence_id,),
                    reason=(
                        "Exactly one verified sibling membership for the same issuer covers the "
                        "entire provisional interval; the row is a duplicate security/ticker split."
                    ),
                )
            )
            continue

        reason_parts: list[str] = []
        if blocker.effective_to is None:
            if len(active_symbols) != 1:
                reason_parts.append("open interval lacks one unique active symbol")
            elif not unique_current:
                reason_parts.append("no pinned current CIK+symbol anchor covers interval start")
            else:
                reason_parts.append("multiple current anchors match")
        if not covering:
            reason_parts.append("no verified sibling covers the whole interval")
        elif len(covering_security_ids) > 1 or len(covering) > 1:
            reason_parts.append("multiple sibling memberships cover interval; share-class ambiguity")
        decisions.append(
            _decision(
                blocker,
                action="unresolved",
                method="unresolved",
                evidence_ids=(),
                reason="; ".join(reason_parts) or "no conservative continuity rule matched",
            )
        )

    return tuple(decisions)


def membership_continuity_plan_id(
    decisions: Sequence[MembershipContinuityDecision],
    *,
    current_source_ref: str,
) -> str:
    return _hash(
        {
            "schema_version": MEMBERSHIP_CONTINUITY_SCHEMA_VERSION,
            "current_source_ref": current_source_ref,
            "decisions": [item.as_dict() for item in sorted(decisions, key=lambda row: row.membership_id)],
        }
    )
