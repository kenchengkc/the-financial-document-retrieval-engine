"""Fail-closed planning for the final HU-5 identity adjudication."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from fdre.research.historical_universe_lineage import normalize_symbol
from fdre.research.historical_universe_membership_continuity import normalize_cik
from fdre.research.historical_universe_residual_sec_evidence import (
    RESIDUAL_SEC_EVIDENCE_SCHEMA_VERSION,
)
from fdre.research.historical_universe_sec_identity import SecTradingSymbolEvidence

IDENTITY_ADJUDICATION_SCHEMA_VERSION = "fdre-hu5-final-identity-adjudication-v1"
EXPECTED_TOPOLOGY_ID = "5e30e1075c71c6578fd60e550ae1518538b680f35c9c9003d4b48372a74821e9"
EXPECTED_TOPOLOGY_AUDIT_ID = "b5dc9108a2cfbbb9d4717aa1cb52dc751e31734bb5188ec5d8e05499db64245a"
EXPECTED_RESIDUAL_SEC_PLAN_ID = (
    "b9e7eebeb8af54f27f051c81a8497be572d31f8de1a79f9c8826c2a4664fe71d"
)
EXPECTED_IDENTITY_ADJUDICATION_MANIFEST_ID = (
    "96628d4fc51ffd0c8322cffd092d8526d286fcf71a262171bb7ebcf042fa8a22"
)
EXPECTED_IDENTITY_ADJUDICATION_PLAN_ID = (
    "d73f752121f42f642f4881e295d7e7b72b56479e276265b7942df274484cc271"
)
EXPECTED_ACTION_COUNTS = {"verify": 37, "correct_and_verify": 5, "insert": 3}
EXPECTED_TOTAL_ACTION_COUNT = 45

IdentityAction = Literal["verify", "correct_and_verify", "insert"]


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

    def as_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "authority": self.authority,
            "source_url": self.source_url,
            "assertion": self.assertion,
        }


@dataclass(frozen=True, slots=True)
class IdentityAnchor:
    identity_id: int
    security_id: int
    cik: str
    symbol: str
    effective_from: date
    effective_to: date | None
    verification_status: str
    source_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "identity_id": self.identity_id,
            "security_id": self.security_id,
            "cik": normalize_cik(self.cik),
            "symbol": normalize_symbol(self.symbol),
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "verification_status": self.verification_status,
            "source_hash": self.source_hash,
        }


@dataclass(frozen=True, slots=True)
class MembershipAnchor:
    membership_id: int
    security_id: int
    cik: str
    universe_code: str
    effective_from: date
    effective_to: date | None
    verification_status: str
    source_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "membership_id": self.membership_id,
            "security_id": self.security_id,
            "cik": normalize_cik(self.cik),
            "universe_code": self.universe_code.strip().lower(),
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "verification_status": self.verification_status,
            "source_hash": self.source_hash,
        }


@dataclass(frozen=True, slots=True)
class CorrectionSpec:
    identity_id: int
    target_from: date | None
    target_to: date | Literal["preserve"] | None
    evidence: tuple[IdentityEvidence, ...]
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
    evidence: tuple[IdentityEvidence, ...]
    name: str
    exchange: str
    reason: str


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
    residual_sec_status: str | None = None
    residual_sec_decision_hash: str | None = None
    residual_sec_evidence_ids: tuple[str, ...] = ()
    residual_sec_inspected_accessions: tuple[str, ...] = ()
    residual_sec_conflicting_accessions: tuple[str, ...] = ()
    evidence: tuple[IdentityEvidence, ...] = ()
    identity_anchors: tuple[IdentityAnchor, ...] = ()
    membership_anchors: tuple[MembershipAnchor, ...] = ()
    name: str | None = None
    exchange: str | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "action": self.action,
            "security_id": self.security_id,
            "cik": normalize_cik(self.cik),
            "symbol": normalize_symbol(self.symbol),
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
            "residual_sec_status": self.residual_sec_status,
            "residual_sec_decision_hash": self.residual_sec_decision_hash,
            "residual_sec_evidence_ids": list(self.residual_sec_evidence_ids),
            "residual_sec_inspected_accessions": list(
                self.residual_sec_inspected_accessions
            ),
            "residual_sec_conflicting_accessions": list(
                self.residual_sec_conflicting_accessions
            ),
            "evidence_ids": sorted(item.evidence_id for item in self.evidence),
            "identity_anchors": [
                item.as_dict()
                for item in sorted(self.identity_anchors, key=lambda value: value.identity_id)
            ],
            "membership_anchors": [
                item.as_dict()
                for item in sorted(
                    self.membership_anchors,
                    key=lambda value: value.membership_id,
                )
            ],
            "name": self.name,
            "exchange": self.exchange,
            "reason": self.reason,
        }

    @property
    def decision_hash(self) -> str:
        return _hash(self.as_dict())


IdentityAdjudicationDecision = IdentityAdjudicationCase


def identity_adjudication_manifest_id(
    cases: Sequence[IdentityAdjudicationCase],
) -> str:
    return _hash(
        {
            "schema_version": IDENTITY_ADJUDICATION_SCHEMA_VERSION,
            "topology_audit_id": EXPECTED_TOPOLOGY_AUDIT_ID,
            "topology_id": EXPECTED_TOPOLOGY_ID,
            "residual_sec_plan_id": EXPECTED_RESIDUAL_SEC_PLAN_ID,
            "cases": [
                item.as_dict() for item in sorted(cases, key=lambda item: item.case_id)
            ],
        }
    )


def identity_adjudication_plan_id(
    decisions: Sequence[IdentityAdjudicationDecision],
    *,
    manifest_id: str,
) -> str:
    return _hash(
        {
            "schema_version": IDENTITY_ADJUDICATION_SCHEMA_VERSION,
            "manifest_id": manifest_id,
            "decision_hashes": [
                item.decision_hash
                for item in sorted(decisions, key=lambda item: item.case_id)
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


def _validate_topology_payload(topology: dict[str, Any]) -> None:
    canonical = {
        "schema_version": topology.get("schema_version"),
        "audit_id": topology.get("audit_id"),
        "targets": topology.get("targets"),
        "gaps": topology.get("gaps"),
    }
    computed_id = _hash(canonical)
    expected = {
        "schema_version": "fdre-hu5-residual-identity-topology-v1",
        "audit_id": EXPECTED_TOPOLOGY_AUDIT_ID,
        "topology_id": EXPECTED_TOPOLOGY_ID,
        "target_count": 39,
        "gap_count": 4,
        "strict_eligible_day_count": 1426,
        "blocked_day_count": 4662,
    }
    actual = {key: topology.get(key) for key in expected}
    if actual != expected or computed_id != EXPECTED_TOPOLOGY_ID:
        raise RuntimeError(
            f"frozen topology drifted: header={actual!r}, computed_id={computed_id}"
        )


def _validate_sec_evidence_records(payload: dict[str, Any]) -> set[str]:
    raw = payload.get("evidence")
    if not isinstance(raw, list):
        raise RuntimeError("SEC evidence must be a list")
    evidence_ids: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise RuntimeError("SEC evidence contains a non-object")
        evidence = SecTradingSymbolEvidence(
            row_id=int(item["row_id"]),
            cik=str(item["cik"]),
            accession_number=str(item["accession_number"]),
            filing_date=date.fromisoformat(str(item["filing_date"])),
            form_type=str(item["form_type"]),
            symbol=str(item["symbol"]),
            source_url=str(item["source_url"]),
            payload_sha256=str(item["payload_sha256"]),
            concept_name=str(item["concept_name"]),
            context_ref=(
                str(item["context_ref"]) if item.get("context_ref") is not None else None
            ),
        )
        if item.get("evidence_id") != evidence.evidence_id:
            raise RuntimeError(
                f"SEC evidence {item.get('evidence_id')!r} failed content replay"
            )
        if evidence.evidence_id in evidence_ids:
            raise RuntimeError("SEC evidence inventory contains duplicate IDs")
        evidence_ids.add(evidence.evidence_id)
    return evidence_ids


def _validate_sec_decision(item: dict[str, Any]) -> str:
    decision_payload = {
        "schema_version": RESIDUAL_SEC_EVIDENCE_SCHEMA_VERSION,
        "identity_id": int(item["identity_id"]),
        "security_id": int(item["security_id"]),
        "cik": str(item["cik"]),
        "symbol": str(item["symbol"]),
        "effective_from": str(item["effective_from"]),
        "effective_to": (
            str(item["effective_to"]) if item.get("effective_to") is not None else None
        ),
        "source_hash": str(item["source_hash"]),
        "status": str(item["status"]),
        "sec_evidence_ids": item.get("sec_evidence_ids"),
        "inspected_accessions": item.get("inspected_accessions"),
        "conflicting_accessions": item.get("conflicting_accessions"),
        "error_accessions": item.get("error_accessions"),
    }
    decision_hash = _hash(decision_payload)
    if item.get("decision_hash") != decision_hash:
        raise RuntimeError(f"SEC decision {item.get('identity_id')} failed content replay")
    return decision_hash


def _validate_residual_sec_payload(
    residual_sec: dict[str, Any],
    *,
    targets: dict[int, dict[str, Any]],
) -> None:
    expected = {
        "schema_version": RESIDUAL_SEC_EVIDENCE_SCHEMA_VERSION,
        "topology_id": EXPECTED_TOPOLOGY_ID,
        "plan_id": EXPECTED_RESIDUAL_SEC_PLAN_ID,
        "target_count": 39,
        "filing_error_count": 0,
        "status_counts": {
            "sec_supported": 22,
            "sec_symbol_conflict": 1,
            "sec_symbol_missing": 16,
        },
    }
    actual = {key: residual_sec.get(key) for key in expected}
    if actual != expected:
        raise RuntimeError(f"frozen residual SEC header drifted: {actual!r}")

    evidence_ids = _validate_sec_evidence_records(residual_sec)
    decisions = _sec_map(residual_sec)
    if set(decisions) != set(targets):
        raise RuntimeError("SEC decision inventory differs from frozen topology")
    decision_hashes: list[tuple[int, str]] = []
    for identity_id, item in decisions.items():
        target = targets[identity_id]
        exact_target = {
            key: target.get(key)
            for key in (
                "identity_id",
                "security_id",
                "cik",
                "symbol",
                "effective_from",
                "effective_to",
                "source_hash",
            )
        }
        actual_target = {key: item.get(key) for key in exact_target}
        if actual_target != exact_target:
            raise RuntimeError(f"SEC decision target {identity_id} drifted")
        ids = item.get("sec_evidence_ids")
        if not isinstance(ids, list) or not all(isinstance(value, str) for value in ids):
            raise RuntimeError(f"SEC decision {identity_id} evidence IDs are invalid")
        if not set(ids).issubset(evidence_ids):
            raise RuntimeError(f"SEC decision {identity_id} references unknown evidence")
        decision_hashes.append((identity_id, _validate_sec_decision(item)))
    computed_plan_id = _hash(
        {
            "schema_version": RESIDUAL_SEC_EVIDENCE_SCHEMA_VERSION,
            "topology_id": EXPECTED_TOPOLOGY_ID,
            "decision_hashes": [
                value for _, value in sorted(decision_hashes, key=lambda pair: pair[0])
            ],
        }
    )
    if computed_plan_id != EXPECTED_RESIDUAL_SEC_PLAN_ID:
        raise RuntimeError(f"residual SEC plan replay drifted: {computed_plan_id}")


def validate_frozen_headers(
    topology: dict[str, Any],
    residual_sec: dict[str, Any],
) -> None:
    _validate_topology_payload(topology)
    _validate_residual_sec_payload(residual_sec, targets=_target_map(topology))


def _optional_date(value: Any) -> date | None:
    return date.fromisoformat(str(value)) if value is not None else None


def _identity_anchors(
    context: dict[str, Any],
    *,
    exclude_identity_id: int | None = None,
) -> tuple[IdentityAnchor, ...]:
    raw = context.get("identity_periods")
    if not isinstance(raw, list):
        raise RuntimeError("identity anchor inventory must be a list")
    anchors = tuple(
        IdentityAnchor(
            identity_id=int(item["identity_id"]),
            security_id=int(item["security_id"]),
            cik=str(context["cik"]),
            symbol=str(item["symbol"]),
            effective_from=date.fromisoformat(str(item["effective_from"])),
            effective_to=_optional_date(item.get("effective_to")),
            verification_status=str(item["verification_status"]),
            source_hash=str(item["source_hash"]),
        )
        for item in raw
        if isinstance(item, dict)
        and int(item["identity_id"]) != exclude_identity_id
    )
    if len(anchors) != len({item.identity_id for item in anchors}):
        raise RuntimeError("identity anchor inventory contains duplicate IDs")
    return tuple(sorted(anchors, key=lambda item: item.identity_id))


def _membership_anchors(context: dict[str, Any]) -> tuple[MembershipAnchor, ...]:
    raw = context.get("memberships")
    if not isinstance(raw, list):
        raise RuntimeError("membership anchor inventory must be a list")
    anchors = tuple(
        MembershipAnchor(
            membership_id=int(item["membership_id"]),
            security_id=int(item["security_id"]),
            cik=str(context["cik"]),
            universe_code=str(item["universe_code"]),
            effective_from=date.fromisoformat(str(item["effective_from"])),
            effective_to=_optional_date(item.get("effective_to")),
            verification_status=str(item["verification_status"]),
            source_hash=str(item["source_hash"]),
        )
        for item in raw
        if isinstance(item, dict)
    )
    if len(anchors) != len({item.membership_id for item in anchors}):
        raise RuntimeError("membership anchor inventory contains duplicate IDs")
    return tuple(sorted(anchors, key=lambda item: item.membership_id))


def _case_from_target(
    target: dict[str, Any],
    sec_decision: dict[str, Any],
    *,
    action: IdentityAction,
    target_from: date | None = None,
    target_to: date | Literal["preserve"] | None = "preserve",
    evidence: tuple[IdentityEvidence, ...] = (),
    reason: str,
) -> IdentityAdjudicationCase:
    period = _target_period(target)
    prior_from = date.fromisoformat(str(target["effective_from"]))
    prior_to = _optional_date(target.get("effective_to"))
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
        residual_sec_status=str(sec_decision["status"]),
        residual_sec_decision_hash=str(sec_decision["decision_hash"]),
        residual_sec_evidence_ids=tuple(sorted(sec_decision["sec_evidence_ids"])),
        residual_sec_inspected_accessions=tuple(
            sec_decision["inspected_accessions"]
        ),
        residual_sec_conflicting_accessions=tuple(
            sec_decision["conflicting_accessions"]
        ),
        evidence=evidence,
        identity_anchors=_identity_anchors(
            target,
            exclude_identity_id=int(target["identity_id"]),
        ),
        membership_anchors=_membership_anchors(target),
        reason=reason,
    )


def _case_from_gap(
    gap: dict[str, Any],
    period: dict[str, Any],
    *,
    spec: CorrectionSpec,
) -> IdentityAdjudicationCase:
    if spec.target_from is None or spec.target_to == "preserve":
        raise RuntimeError(f"gap correction {spec.identity_id} has incomplete boundaries")
    return IdentityAdjudicationCase(
        case_id=(
            f"correct_and_verify-{spec.identity_id}-"
            f"{str(period['symbol']).lower()}"
        ),
        action="correct_and_verify",
        security_id=int(gap["security_id"]),
        cik=str(gap["cik"]),
        symbol=str(period["symbol"]),
        existing_identity_id=spec.identity_id,
        prior_effective_from=date.fromisoformat(str(period["effective_from"])),
        prior_effective_to=_optional_date(period.get("effective_to")),
        prior_source_hash=str(period["source_hash"]),
        prior_verification_status=str(period["verification_status"]),
        target_effective_from=spec.target_from,
        target_effective_to=spec.target_to,
        evidence=spec.evidence,
        identity_anchors=_identity_anchors(
            gap,
            exclude_identity_id=spec.identity_id,
        ),
        membership_anchors=_membership_anchors(gap),
        reason=spec.reason,
    )


def _insert_context(
    topology: dict[str, Any],
    *,
    security_id: int,
) -> dict[str, Any]:
    contexts = [
        item
        for key in ("targets", "gaps")
        for item in topology.get(key, [])
        if isinstance(item, dict) and int(item["security_id"]) == security_id
    ]
    if not contexts:
        raise RuntimeError(f"insert security {security_id} is absent from frozen topology")
    first = contexts[0]
    expected = {
        "cik": first.get("cik"),
        "identity_periods": first.get("identity_periods"),
        "memberships": first.get("memberships"),
    }
    if any(
        {key: item.get(key) for key in expected} != expected for item in contexts[1:]
    ):
        raise RuntimeError(f"insert security {security_id} topology contexts disagree")
    return first


def _case_from_insert(
    topology: dict[str, Any],
    *,
    spec: InsertSpec,
) -> IdentityAdjudicationCase:
    context = _insert_context(topology, security_id=spec.security_id)
    if normalize_cik(str(context["cik"])) != normalize_cik(spec.cik):
        raise RuntimeError(f"insert {spec.case_id} CIK differs from frozen topology")
    return IdentityAdjudicationCase(
        case_id=spec.case_id,
        action="insert",
        security_id=spec.security_id,
        cik=spec.cik,
        symbol=spec.symbol,
        target_effective_from=spec.target_from,
        target_effective_to=spec.target_to,
        evidence=spec.evidence,
        identity_anchors=_identity_anchors(context),
        membership_anchors=_membership_anchors(context),
        name=spec.name,
        exchange=spec.exchange,
        reason=spec.reason,
    )


def _validate_case_shape(case: IdentityAdjudicationCase) -> None:
    if not case.case_id or not case.reason:
        raise ValueError("identity adjudication cases require a case ID and reason")
    if normalize_cik(case.cik) != case.cik or len(case.cik) != 10:
        raise ValueError(f"case {case.case_id} CIK must be normalized")
    if normalize_symbol(case.symbol) != case.symbol:
        raise ValueError(f"case {case.case_id} symbol must be normalized")
    if case.target_effective_to is not None and (
        case.target_effective_to <= case.target_effective_from
    ):
        raise ValueError(f"case {case.case_id} has a non-positive target interval")

    prior = (case.prior_effective_from, case.prior_effective_to)
    target = (case.target_effective_from, case.target_effective_to)
    if case.action == "insert":
        if (
            case.existing_identity_id is not None
            or case.prior_effective_from is not None
            or case.prior_effective_to is not None
            or case.prior_source_hash is not None
            or case.prior_verification_status is not None
        ):
            raise ValueError(f"insert {case.case_id} cannot bind a prior row")
        if not case.name or not case.exchange or not case.evidence:
            raise ValueError(f"insert {case.case_id} requires identity fields and evidence")
        return

    if (
        case.existing_identity_id is None
        or case.prior_effective_from is None
        or not case.prior_source_hash
        or not case.prior_verification_status
    ):
        raise ValueError(f"existing-row case {case.case_id} lacks a prior-row anchor")
    if case.action == "verify" and prior != target:
        raise ValueError(f"verify case {case.case_id} cannot change boundaries")
    if case.action == "correct_and_verify" and prior == target:
        raise ValueError(
            f"correct_and_verify case {case.case_id} must change a boundary"
        )
    if not case.membership_anchors:
        raise ValueError(f"existing-row case {case.case_id} lacks membership anchors")


def _validate_continuity(case: IdentityAdjudicationCase) -> None:
    adjacent = [
        item
        for item in case.identity_anchors
        if item.verification_status == "verified"
        and item.symbol == case.symbol
        and (
            item.effective_to == case.target_effective_from
            or (
                case.target_effective_to is not None
                and item.effective_from == case.target_effective_to
            )
        )
    ]
    if len(adjacent) != 1:
        raise RuntimeError(
            f"identity {case.existing_identity_id} lost its unique verified continuity anchor"
        )


def _overlaps(
    left_start: date,
    left_end: date | None,
    right_start: date,
    right_end: date | None,
) -> bool:
    return (right_end is None or left_start < right_end) and (
        left_end is None or right_start < left_end
    )


def _validate_final_identity_intervals(
    cases: Sequence[IdentityAdjudicationCase],
) -> None:
    existing_ids = {
        item.existing_identity_id
        for item in cases
        if item.existing_identity_id is not None
    }
    rows: dict[int, tuple[int, str, date, date | None, str]] = {}
    for case in cases:
        row_key = case.existing_identity_id
        if row_key is None:
            row_key = -len(rows) - 1
        rows[row_key] = (
            case.security_id,
            case.symbol,
            case.target_effective_from,
            case.target_effective_to,
            "verified",
        )
        for anchor in case.identity_anchors:
            if (
                anchor.identity_id in existing_ids
                or anchor.verification_status == "rejected"
            ):
                continue
            value = (
                anchor.security_id,
                anchor.symbol,
                anchor.effective_from,
                anchor.effective_to,
                anchor.verification_status,
            )
            prior = rows.setdefault(anchor.identity_id, value)
            if prior != value:
                raise RuntimeError(
                    f"identity anchor {anchor.identity_id} differs across reviewed cases"
                )

    by_security: dict[int, list[tuple[int, str, date, date | None]]] = {}
    for row_id, (security_id, symbol, start, end, _) in rows.items():
        by_security.setdefault(security_id, []).append((row_id, symbol, start, end))
    for security_id, intervals in by_security.items():
        ordered = sorted(intervals, key=lambda item: (item[2], item[0]))
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                if _overlaps(left[2], left[3], right[2], right[3]):
                    raise RuntimeError(
                        f"reviewed identities overlap for security {security_id}: "
                        f"{left[0]}:{left[1]} and {right[0]}:{right[1]}"
                    )


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
    if len(set(verify_identity_ids)) != len(verify_identity_ids):
        raise RuntimeError("reviewed verify inventory contains duplicate identity IDs")
    correction_ids = [item.identity_id for item in correction_specs]
    if len(set(correction_ids)) != len(correction_ids):
        raise RuntimeError("reviewed correction inventory contains duplicate identity IDs")
    if not continuity_verify_ids.issubset(verify_identity_ids):
        raise RuntimeError("continuity inventory contains a non-verify identity")
    expected_target_ids = set(verify_identity_ids) | {
        item.identity_id for item in correction_specs if item.identity_id in targets
    }
    if set(targets) != expected_target_ids or set(sec) != set(targets):
        raise RuntimeError("reviewed target inventory does not equal the frozen 39-row topology")

    decisions: list[IdentityAdjudicationCase] = []
    for identity_id in verify_identity_ids:
        target = targets[identity_id]
        sec_decision = sec[identity_id]
        evidence = authoritative_verify_evidence.get(identity_id, ())
        case = _case_from_target(
            target,
            sec_decision,
            action="verify",
            evidence=evidence,
            reason=f"Verify frozen residual identity {identity_id} from reviewed evidence.",
        )
        if identity_id in continuity_verify_ids:
            _validate_continuity(case)
        elif case.residual_sec_status == "sec_supported":
            if not case.residual_sec_evidence_ids:
                raise RuntimeError(f"SEC-supported identity {identity_id} has no evidence IDs")
        elif not evidence:
            raise RuntimeError(f"verify identity {identity_id} has no reviewed support")
        decisions.append(case)

    gap_periods: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
    gaps = topology.get("gaps")
    if not isinstance(gaps, list):
        raise RuntimeError("topology gaps must be a list")
    for gap in gaps:
        if not isinstance(gap, dict):
            raise RuntimeError("topology gap must be an object")
        periods = gap.get("identity_periods")
        if not isinstance(periods, list):
            raise RuntimeError("topology gap identity periods must be a list")
        for period in periods:
            if not isinstance(period, dict):
                raise RuntimeError("topology gap period must be an object")
            identity_id = int(period["identity_id"])
            if identity_id in gap_periods:
                raise RuntimeError(f"gap identity {identity_id} is not unique")
            gap_periods[identity_id] = (gap, period)

    for spec in correction_specs:
        identity_id = spec.identity_id
        if identity_id in targets:
            if sec[identity_id].get("status") != spec.sec_status:
                raise RuntimeError(f"SEC status drifted for correction {identity_id}")
            case = _case_from_target(
                targets[identity_id],
                sec[identity_id],
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
            case = _case_from_gap(gap_pair[0], gap_pair[1], spec=spec)
        decisions.append(case)

    decisions.extend(_case_from_insert(topology, spec=spec) for spec in insert_specs)
    counts = {
        action: sum(item.action == action for item in decisions)
        for action in EXPECTED_ACTION_COUNTS
    }
    if counts != EXPECTED_ACTION_COUNTS or len(decisions) != EXPECTED_TOTAL_ACTION_COUNT:
        raise RuntimeError(f"reviewed action topology changed: {counts}")
    case_ids = [item.case_id for item in decisions]
    existing_row_ids = [
        item.existing_identity_id
        for item in decisions
        if item.existing_identity_id is not None
    ]
    if len(set(case_ids)) != len(case_ids):
        raise RuntimeError("reviewed action topology contains duplicate case IDs")
    if len(set(existing_row_ids)) != len(existing_row_ids):
        raise RuntimeError("reviewed action topology contains duplicate target IDs")
    for case in decisions:
        _validate_case_shape(case)
        if case.action in {"correct_and_verify", "insert"} and not case.evidence:
            raise RuntimeError(f"case {case.case_id} lacks authoritative evidence")
    _validate_final_identity_intervals(decisions)
    ordered = tuple(sorted(decisions, key=lambda item: item.case_id))
    manifest_id = identity_adjudication_manifest_id(ordered)
    plan_id = identity_adjudication_plan_id(ordered, manifest_id=manifest_id)
    if manifest_id != EXPECTED_IDENTITY_ADJUDICATION_MANIFEST_ID:
        raise RuntimeError(f"reviewed identity manifest drifted: {manifest_id}")
    if plan_id != EXPECTED_IDENTITY_ADJUDICATION_PLAN_ID:
        raise RuntimeError(f"reviewed identity plan drifted: {plan_id}")
    return ordered
