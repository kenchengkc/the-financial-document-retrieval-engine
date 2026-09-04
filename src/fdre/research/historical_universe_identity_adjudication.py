"""Fail-closed planning for the final HU-5 identity adjudication."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

IDENTITY_ADJUDICATION_SCHEMA_VERSION = "fdre-hu5-final-identity-adjudication-v1"
EXPECTED_TOPOLOGY_ID = "5e30e1075c71c6578fd60e550ae1518538b680f35c9c9003d4b48372a74821e9"
EXPECTED_TOPOLOGY_AUDIT_ID = "b5dc9108a2cfbbb9d4717aa1cb52dc751e31734bb5188ec5d8e05499db64245a"
EXPECTED_RESIDUAL_SEC_PLAN_ID = (
    "b9e7eebeb8af54f27f051c81a8497be572d31f8de1a79f9c8826c2a4664fe71d"
)
EXPECTED_ACTION_COUNTS = {"verify": 37, "correct_and_verify": 5, "insert": 3}
EXPECTED_TOTAL_ACTION_COUNT = 45

IdentityAction = Literal["verify", "correct_and_verify", "insert"]


@dataclass(frozen=True, slots=True)
class CorrectionSpec:
    identity_id: int
    target_from: date | None
    target_to: date | None | Literal["preserve"]
    evidence: tuple["IdentityEvidence", ...]
    reason: str
    sec_status: str | None = None


@dataclass(frozen=True, slots=True)
class InsertSpec:
    case_id: str
    security_id: int
    cik: str
    symbol: str
    target_from: date
    target_to: date | None
    evidence: tuple["IdentityEvidence", ...]
    name: str
    exchange: str
    reason: str


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class IdentityEvidence:
    authority: str
    source_url: str
    assertion: str

    @property
    def evidence_id(self) -> str:
        return _hash(
            {
                "authority": self.authority,
                "source_url": self.source_url,
                "assertion": self.assertion,
            }
        )


@dataclass(frozen=True, slots=True)
class IdentityAdjudicationCase:
    case_id: str
    action: IdentityAction
    security_id: int
    cik: str
    symbol: str
    target_effective_from: date
    target_effective_to: date | None
    existing_identity_id: int | None = None
    prior_effective_from: date | None = None
    prior_effective_to: date | None = None
    prior_source_hash: str | None = None
    prior_verification_status: str | None = None
    evidence: tuple[IdentityEvidence, ...] = ()
    name: str | None = None
    exchange: str | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "action": self.action,
            "security_id": self.security_id,
            "cik": self.cik,
            "symbol": self.symbol,
            "existing_identity_id": self.existing_identity_id,
            "prior_effective_from": (
                self.prior_effective_from.isoformat() if self.prior_effective_from else None
            ),
            "prior_effective_to": (
                self.prior_effective_to.isoformat() if self.prior_effective_to else None
            ),
            "prior_source_hash": self.prior_source_hash,
            "prior_verification_status": self.prior_verification_status,
            "target_effective_from": self.target_effective_from.isoformat(),
            "target_effective_to": (
                self.target_effective_to.isoformat() if self.target_effective_to else None
            ),
            "evidence_ids": sorted(item.evidence_id for item in self.evidence),
            "name": self.name,
            "exchange": self.exchange,
            "reason": self.reason,
        }

    @property
    def decision_hash(self) -> str:
        return _hash(self.as_dict())


IdentityAdjudicationDecision = IdentityAdjudicationCase


def identity_adjudication_manifest_id(cases: tuple[IdentityAdjudicationCase, ...]) -> str:
    return _hash(
        {
            "schema_version": IDENTITY_ADJUDICATION_SCHEMA_VERSION,
            "topology_id": EXPECTED_TOPOLOGY_ID,
            "residual_sec_plan_id": EXPECTED_RESIDUAL_SEC_PLAN_ID,
            "cases": [
                item.as_dict() for item in sorted(cases, key=lambda item: item.case_id)
            ],
        }
    )


def identity_adjudication_plan_id(
    decisions: tuple[IdentityAdjudicationDecision, ...],
    *,
    manifest_id: str,
) -> str:
    return _hash(
        {
            "schema_version": IDENTITY_ADJUDICATION_SCHEMA_VERSION,
            "manifest_id": manifest_id,
            "decisions": [
                item.as_dict() for item in sorted(decisions, key=lambda item: item.case_id)
            ],
        }
    )


def _target_map(topology: dict[str, Any]) -> dict[int, dict[str, Any]]:
    raw = topology.get("targets")
    if not isinstance(raw, list):
        raise RuntimeError("topology targets must be a list")
    result = {int(item["identity_id"]): item for item in raw if isinstance(item, dict)}
    if len(result) != len(raw):
        raise RuntimeError("topology targets contain duplicates or invalid rows")
    return result


def _sec_map(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    raw = payload.get("decisions")
    if not isinstance(raw, list):
        raise RuntimeError("SEC decisions must be a list")
    result = {int(item["identity_id"]): item for item in raw if isinstance(item, dict)}
    if len(result) != len(raw):
        raise RuntimeError("SEC decisions contain duplicates or invalid rows")
    return result


def _target_period(target: dict[str, Any]) -> dict[str, Any]:
    periods = target.get("identity_periods")
    if not isinstance(periods, list):
        raise RuntimeError("target identity_periods must be a list")
    identity_id = int(target["identity_id"])
    matches = [
        item
        for item in periods
        if isinstance(item, dict) and int(item.get("identity_id", -1)) == identity_id
    ]
    if len(matches) != 1:
        raise RuntimeError(f"target identity {identity_id} is not unique in frozen topology")
    return matches[0]


def _case_from_target(
    target: dict[str, Any],
    *,
    action: IdentityAction,
    target_from: date | None = None,
    target_to: date | None | Literal["preserve"] = "preserve",
    evidence: tuple[IdentityEvidence, ...] = (),
    reason: str,
) -> IdentityAdjudicationCase:
    period = _target_period(target)
    prior_from = date.fromisoformat(str(target["effective_from"]))
    prior_to = (
        date.fromisoformat(str(target["effective_to"])) if target.get("effective_to") else None
    )
    resolved_to = prior_to if target_to == "preserve" else target_to
    return IdentityAdjudicationCase(
        case_id=f"{action}-{int(target['identity_id'])}-{str(target['symbol']).lower()}",
        action=action,
        security_id=int(target["security_id"]),
        cik=str(target["cik"]),
        symbol=str(target["symbol"]),
        existing_identity_id=int(target["identity_id"]),
        prior_effective_from=prior_from,
        prior_effective_to=prior_to,
        prior_source_hash=str(target["source_hash"]),
        prior_verification_status=str(period["verification_status"]),
        target_effective_from=target_from or prior_from,
        target_effective_to=resolved_to,
        evidence=evidence,
        reason=reason,
    )


def _validate_continuity(target: dict[str, Any]) -> None:
    period = _target_period(target)
    periods = target["identity_periods"]
    symbol = str(target["symbol"])
    prior_from = str(target["effective_from"])
    prior_to = target.get("effective_to")
    anchors = [
        item
        for item in periods
        if isinstance(item, dict)
        and int(item["identity_id"]) != int(target["identity_id"])
        and item.get("verification_status") == "verified"
        and item.get("symbol") == symbol
        and (
            item.get("effective_to") == prior_from
            or (prior_to is not None and item.get("effective_from") == prior_to)
        )
    ]
    if len(anchors) != 1:
        raise RuntimeError(
            f"identity {target['identity_id']} lost its unique verified continuity anchor"
        )
    if period.get("verification_status") != "provisional":
        raise RuntimeError(f"identity {target['identity_id']} is no longer provisional")


def validate_frozen_headers(
    topology: dict[str, Any],
    residual_sec: dict[str, Any],
) -> None:
    expected_topology = {
        "schema_version": "fdre-hu5-identity-topology-v1",
        "audit_id": EXPECTED_TOPOLOGY_AUDIT_ID,
        "topology_id": EXPECTED_TOPOLOGY_ID,
        "target_count": 39,
        "gap_count": 4,
        "strict_eligible_day_count": 1426,
        "blocked_day_count": 4662,
    }
    actual_topology = {key: topology.get(key) for key in expected_topology}
    if actual_topology != expected_topology:
        raise RuntimeError(f"frozen topology header drifted: {actual_topology!r}")
    expected_sec = {
        "schema_version": "fdre-hu5-residual-sec-evidence-v1",
        "topology_id": EXPECTED_TOPOLOGY_ID,
        "plan_id": EXPECTED_RESIDUAL_SEC_PLAN_ID,
        "target_count": 39,
        "filing_error_count": 0,
        "status_counts": {
            "sec_fetch_error": 0,
            "sec_supported": 22,
            "sec_symbol_conflict": 1,
            "sec_symbol_missing": 16,
        },
    }
    actual_sec = {key: residual_sec.get(key) for key in expected_sec}
    if actual_sec != expected_sec:
        raise RuntimeError(f"frozen residual SEC header drifted: {actual_sec!r}")


def build_reviewed_identity_plan(
    *,
    topology: dict[str, Any],
    residual_sec: dict[str, Any],
    verify_identity_ids: tuple[int, ...],
    continuity_verify_ids: frozenset[int],
    authoritative_verify_evidence: dict[int, tuple[IdentityEvidence, ...]],
    correction_specs: tuple[CorrectionSpec, ...],
    insert_specs: tuple[InsertSpec, ...],
) -> tuple[IdentityAdjudicationDecision, ...]:
    """Bind the compact reviewed manifest to exact frozen production artifacts."""

    validate_frozen_headers(topology, residual_sec)
    targets = _target_map(topology)
    sec = _sec_map(residual_sec)
    expected_target_ids = set(verify_identity_ids) | {
        item.identity_id for item in correction_specs if item.identity_id in targets
    }
    if set(targets) != expected_target_ids or set(sec) != set(targets):
        raise RuntimeError("reviewed target inventory does not equal the frozen 39-row topology")

    decisions: list[IdentityAdjudicationCase] = []
    for identity_id in verify_identity_ids:
        target = targets[identity_id]
        status = sec[identity_id].get("status")
        evidence = authoritative_verify_evidence.get(identity_id, ())
        if identity_id in continuity_verify_ids:
            _validate_continuity(target)
        elif status != "sec_supported" and not evidence:
            raise RuntimeError(f"verify identity {identity_id} has no reviewed support")
        decisions.append(
            _case_from_target(
                target,
                action="verify",
                evidence=evidence,
                reason=f"Verify frozen residual identity {identity_id} from reviewed evidence.",
            )
        )

    gaps = topology.get("gaps")
    if not isinstance(gaps, list):
        raise RuntimeError("topology gaps must be a list")
    gap_periods = {
        int(period["identity_id"]): (gap, period)
        for gap in gaps
        if isinstance(gap, dict)
        for period in gap.get("identity_periods", [])
        if isinstance(period, dict)
    }
    for spec in correction_specs:
        identity_id = spec.identity_id
        if identity_id in targets:
            target = targets[identity_id]
            if sec[identity_id].get("status") != spec.sec_status:
                raise RuntimeError(f"SEC status drifted for correction {identity_id}")
            case = _case_from_target(
                target,
                action="correct_and_verify",
                target_from=spec.target_from,
                target_to=spec.target_to,
                evidence=spec.evidence,
                reason=spec.reason,
            )
        else:
            gap_pair = gap_periods.get(identity_id)
            if gap_pair is None:
                raise RuntimeError(f"gap correction identity {identity_id} disappeared")
            gap, period = gap_pair
            if spec.target_from is None or spec.target_to == "preserve":
                raise RuntimeError(f"gap correction {identity_id} has incomplete boundaries")
            case = IdentityAdjudicationCase(
                case_id=f"correct_and_verify-{identity_id}-{str(period['symbol']).lower()}",
                action="correct_and_verify",
                security_id=int(gap["security_id"]),
                cik=str(gap["cik"]),
                symbol=str(period["symbol"]),
                existing_identity_id=identity_id,
                prior_effective_from=date.fromisoformat(str(period["effective_from"])),
                prior_effective_to=(
                    date.fromisoformat(str(period["effective_to"]))
                    if period.get("effective_to")
                    else None
                ),
                prior_source_hash=str(period["source_hash"]),
                prior_verification_status=str(period["verification_status"]),
                target_effective_from=spec.target_from,
                target_effective_to=spec.target_to,
                evidence=spec.evidence,
                reason=spec.reason,
            )
        decisions.append(case)

    for spec in insert_specs:
        decisions.append(
            IdentityAdjudicationCase(
                case_id=spec.case_id,
                action="insert",
                security_id=spec.security_id,
                cik=spec.cik,
                symbol=spec.symbol,
                target_effective_from=spec.target_from,
                target_effective_to=spec.target_to,
                evidence=spec.evidence,
                name=spec.name,
                exchange=spec.exchange,
                reason=spec.reason,
            )
        )

    counts = {
        action: sum(item.action == action for item in decisions)
        for action in EXPECTED_ACTION_COUNTS
    }
    if counts != EXPECTED_ACTION_COUNTS or len(decisions) != EXPECTED_TOTAL_ACTION_COUNT:
        raise RuntimeError(f"reviewed action topology changed: {counts}")
    return tuple(sorted(decisions, key=lambda item: item.case_id))
