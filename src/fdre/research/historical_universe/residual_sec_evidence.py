"""Pure SEC issuer→symbol evidence decisions for residual HU-5 identity blockers.

Unlike the earlier broad SEC identity projection, this layer does not use ticker-state
containment to choose whether a filing may be inspected. Target identity rows have already been
selected by the frozen identity-aware coverage audit and topology projection. This module answers
only whether filings under the exact issuer CIK explicitly bind that issuer to the target trading
symbol.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

from fdre.research.historical_universe_sec_identity import (
    SecIdentityFilingObservation,
    sec_symbol_match_key,
)

RESIDUAL_SEC_EVIDENCE_SCHEMA_VERSION = "fdre-hu5-residual-sec-evidence-v1"
ResidualSecStatus = Literal[
    "sec_supported",
    "sec_symbol_missing",
    "sec_symbol_conflict",
    "sec_fetch_error",
]


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ResidualSecTarget:
    identity_id: int
    security_id: int
    cik: str
    symbol: str
    effective_from: date
    effective_to: date | None
    source_hash: str

    def __post_init__(self) -> None:
        if self.identity_id <= 0 or self.security_id <= 0:
            raise ValueError("identity_id and security_id must be positive")
        if not self.cik.isdigit() or len(self.cik) != 10:
            raise ValueError("cik must be a zero-padded 10-digit string")
        if len(self.source_hash) != 64:
            raise ValueError("source_hash must be a SHA-256 digest")

    def as_dict(self) -> dict[str, object]:
        return {
            "identity_id": self.identity_id,
            "security_id": self.security_id,
            "cik": self.cik,
            "symbol": self.symbol,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "source_hash": self.source_hash,
        }


@dataclass(frozen=True, slots=True)
class ResidualSecDecision:
    identity_id: int
    security_id: int
    cik: str
    symbol: str
    effective_from: date
    effective_to: date | None
    source_hash: str
    status: ResidualSecStatus
    sec_evidence_ids: tuple[str, ...]
    inspected_accessions: tuple[str, ...]
    conflicting_accessions: tuple[str, ...]
    error_accessions: tuple[str, ...]
    decision_hash: str

    @property
    def supported(self) -> bool:
        return self.status == "sec_supported"

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["effective_from"] = self.effective_from.isoformat()
        payload["effective_to"] = self.effective_to.isoformat() if self.effective_to else None
        payload["supported"] = self.supported
        return payload


def plan_residual_sec_evidence(
    targets: tuple[ResidualSecTarget, ...],
    observations: tuple[SecIdentityFilingObservation, ...],
) -> tuple[ResidualSecDecision, ...]:
    """Classify exact CIK→symbol filing evidence for a frozen set of identity targets."""
    target_ids = [item.identity_id for item in targets]
    if len(target_ids) != len(set(target_ids)):
        raise ValueError("residual SEC target identity IDs must be unique")
    known = set(target_ids)
    if any(item.row_id not in known for item in observations):
        raise ValueError("SEC observation references an identity outside the frozen target set")

    observations_by_row: dict[int, list[SecIdentityFilingObservation]] = {}
    for observation in observations:
        observations_by_row.setdefault(observation.row_id, []).append(observation)

    decisions: list[ResidualSecDecision] = []
    for target in sorted(targets, key=lambda item: item.identity_id):
        target_key = sec_symbol_match_key(target.symbol)
        row_observations = sorted(
            observations_by_row.get(target.identity_id, []),
            key=lambda item: (item.filing_date, item.accession_number),
        )
        inspected = tuple(item.accession_number for item in row_observations)
        errors = tuple(
            item.accession_number for item in row_observations if item.error is not None
        )
        conflicts = tuple(
            item.accession_number
            for item in row_observations
            if item.symbols
            and target_key not in {sec_symbol_match_key(symbol) for symbol in item.symbols}
        )
        evidence_ids = tuple(
            sorted(
                {
                    evidence_id
                    for item in row_observations
                    for symbol, evidence_id in item.facts
                    if sec_symbol_match_key(symbol) == target_key
                }
            )
        )

        if errors:
            status: ResidualSecStatus = "sec_fetch_error"
        elif conflicts:
            status = "sec_symbol_conflict"
        elif evidence_ids:
            status = "sec_supported"
        else:
            status = "sec_symbol_missing"

        decision_payload = {
            "schema_version": RESIDUAL_SEC_EVIDENCE_SCHEMA_VERSION,
            **target.as_dict(),
            "status": status,
            "sec_evidence_ids": list(evidence_ids),
            "inspected_accessions": list(inspected),
            "conflicting_accessions": list(conflicts),
            "error_accessions": list(errors),
        }
        decisions.append(
            ResidualSecDecision(
                identity_id=target.identity_id,
                security_id=target.security_id,
                cik=target.cik,
                symbol=target.symbol,
                effective_from=target.effective_from,
                effective_to=target.effective_to,
                source_hash=target.source_hash,
                status=status,
                sec_evidence_ids=evidence_ids,
                inspected_accessions=inspected,
                conflicting_accessions=conflicts,
                error_accessions=errors,
                decision_hash=_digest(decision_payload),
            )
        )
    return tuple(decisions)


def residual_sec_plan_id(
    decisions: tuple[ResidualSecDecision, ...],
    *,
    topology_id: str,
) -> str:
    if len(topology_id) != 64:
        raise ValueError("topology_id must be a SHA-256 digest")
    return _digest(
        {
            "schema_version": RESIDUAL_SEC_EVIDENCE_SCHEMA_VERSION,
            "topology_id": topology_id,
            "decision_hashes": [
                item.decision_hash
                for item in sorted(decisions, key=lambda decision: decision.identity_id)
            ],
        }
    )
