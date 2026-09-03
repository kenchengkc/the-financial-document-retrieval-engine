"""Fail-closed validation helpers for applying the frozen SGPPRB membership rejection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date

from fdre.research.historical_universe_security_type import (
    SEC_SECURITY_TYPE_DECISION_SCHEMA_VERSION,
    SecSecurityTypeEvidence,
    security_symbol_key,
)

SGPPRB_APPLY_SCHEMA_VERSION = "fdre-hu-sgpprb-rejection-apply-v1"
SGPPRB_PROJECTION_SCHEMA_VERSION = "fdre-hu-security-type-adjudication-projection-v2"
SGPPRB_MEMBERSHIP_ID = 580
SGPPRB_IDENTITY_ID = 1082
SGPPRB_SECURITY_ID = 798
SGPPRB_CIK = "0000310158"
SGPPRB_SYMBOL = "SGPPRB"
SGPPRB_SOURCE_SUFFIX = "+sec/noncommon-reject"


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _as_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"projection {field} must be an integer")
    return value


def _as_str(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"projection {field} must be a non-empty string")
    return value


def _as_optional_str(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _as_str(value, field=field)


def _as_dict(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RuntimeError(f"projection {field} must be an object")
    return dict(value)


def _as_list(value: object, *, field: str) -> list[object]:
    if not isinstance(value, list):
        raise RuntimeError(f"projection {field} must be a list")
    return value


def _decision_hash(decision: dict[str, object]) -> str:
    return _digest(
        {
            "schema_version": SEC_SECURITY_TYPE_DECISION_SCHEMA_VERSION,
            "row_kind": _as_str(decision.get("row_kind"), field="decision.row_kind"),
            "row_id": _as_int(decision.get("row_id"), field="decision.row_id"),
            "security_id": _as_int(decision.get("security_id"), field="decision.security_id"),
            "cik": _as_str(decision.get("cik"), field="decision.cik"),
            "symbol": _as_str(decision.get("symbol"), field="decision.symbol"),
            "effective_from": _as_str(
                decision.get("effective_from"), field="decision.effective_from"
            ),
            "effective_to": _as_optional_str(
                decision.get("effective_to"), field="decision.effective_to"
            ),
            "prior_source_hash": _as_str(
                decision.get("prior_source_hash"), field="decision.prior_source_hash"
            ),
            "status": _as_str(decision.get("status"), field="decision.status"),
            "evidence_id": _as_optional_str(
                decision.get("evidence_id"), field="decision.evidence_id"
            ),
        }
    )


def _plan_id(decisions: tuple[dict[str, object], ...]) -> str:
    return _digest(
        {
            "schema_version": SEC_SECURITY_TYPE_DECISION_SCHEMA_VERSION,
            "decision_hashes": [
                _as_str(item.get("decision_hash"), field="decision.decision_hash")
                for item in decisions
            ],
        }
    )


def _evidence_from_dict(payload: dict[str, object]) -> SecSecurityTypeEvidence:
    evidence = SecSecurityTypeEvidence(
        cik=_as_str(payload.get("cik"), field="sec_evidence.cik"),
        listed_symbol=_as_str(
            payload.get("listed_symbol"), field="sec_evidence.listed_symbol"
        ),
        security_type=_as_str(
            payload.get("security_type"), field="sec_evidence.security_type"
        ),  # type: ignore[arg-type]
        common_symbol=_as_str(
            payload.get("common_symbol"), field="sec_evidence.common_symbol"
        ),
        source_url=_as_str(payload.get("source_url"), field="sec_evidence.source_url"),
        payload_sha256=_as_str(
            payload.get("payload_sha256"), field="sec_evidence.payload_sha256"
        ),
        assertion=_as_str(payload.get("assertion"), field="sec_evidence.assertion"),
    )
    claimed = _as_str(payload.get("evidence_id"), field="sec_evidence.evidence_id")
    if evidence.evidence_id != claimed:
        raise RuntimeError(
            f"SEC security-type evidence hash mismatch: expected {claimed}, "
            f"computed {evidence.evidence_id}"
        )
    return evidence


@dataclass(frozen=True, slots=True)
class ValidatedSgpprbRejection:
    plan_id: str
    evidence: SecSecurityTypeEvidence
    decision_hash: str
    prior_source_hash: str
    effective_from: date
    effective_to: date | None


def validate_sgpprb_projection(
    payload: dict[str, object],
    *,
    expected_plan_id: str,
) -> ValidatedSgpprbRejection:
    """Validate the exact frozen SGPPRB projection before any production write."""

    if payload.get("schema_version") != SGPPRB_PROJECTION_SCHEMA_VERSION:
        raise RuntimeError("unsupported SGPPRB projection schema")
    if payload.get("mode") != "projection" or payload.get("applied") is not False:
        raise RuntimeError("SGPPRB apply requires an unapplied projection")
    claimed_plan = _as_str(payload.get("plan_id"), field="plan_id")
    if claimed_plan != expected_plan_id:
        raise RuntimeError(
            f"SGPPRB plan drift: expected {expected_plan_id}, got {claimed_plan}"
        )
    if _as_int(
        payload.get("known_blocker_membership_id"), field="known_blocker_membership_id"
    ) != SGPPRB_MEMBERSHIP_ID:
        raise RuntimeError("SGPPRB blocker membership changed")
    if _as_str(payload.get("target_sec_cik"), field="target_sec_cik") != SGPPRB_CIK:
        raise RuntimeError("SGPPRB issuer CIK changed")
    if security_symbol_key(
        _as_str(payload.get("target_symbol"), field="target_symbol")
    ) != SGPPRB_SYMBOL:
        raise RuntimeError("SGPPRB target symbol changed")
    if _as_int(payload.get("target_count"), field="target_count") != 2:
        raise RuntimeError("SGPPRB projection must contain exactly two adjudication targets")
    if _as_int(
        payload.get("rejection_candidate_count"), field="rejection_candidate_count"
    ) != 1:
        raise RuntimeError("SGPPRB projection must contain exactly one rejection candidate")
    if _as_int(payload.get("staged_rejection_count"), field="staged_rejection_count") != 1:
        raise RuntimeError("SGPPRB projection must stage exactly one rejection")

    evidence = _evidence_from_dict(
        _as_dict(payload.get("sec_evidence"), field="sec_evidence")
    )
    if evidence.cik != SGPPRB_CIK:
        raise RuntimeError("SEC evidence CIK does not match frozen SGPPRB issuer")
    if security_symbol_key(evidence.listed_symbol) != SGPPRB_SYMBOL:
        raise RuntimeError("SEC evidence does not identify SGPPRB")
    if evidence.security_type != "preferred_stock":
        raise RuntimeError("SEC evidence no longer classifies SGPPRB as preferred stock")
    if security_symbol_key(evidence.common_symbol) == SGPPRB_SYMBOL:
        raise RuntimeError("SEC evidence does not distinguish the issuer common symbol")

    raw_decisions = _as_list(payload.get("decisions"), field="decisions")
    decisions: list[dict[str, object]] = []
    seen: set[tuple[str, int]] = set()
    for raw in raw_decisions:
        decision = _as_dict(raw, field="decision")
        key = (
            _as_str(decision.get("row_kind"), field="decision.row_kind"),
            _as_int(decision.get("row_id"), field="decision.row_id"),
        )
        if key in seen:
            raise RuntimeError(f"duplicate SGPPRB decision {key[0]}:{key[1]}")
        seen.add(key)
        claimed_hash = _as_str(
            decision.get("decision_hash"), field="decision.decision_hash"
        )
        computed_hash = _decision_hash(decision)
        if claimed_hash != computed_hash:
            raise RuntimeError(
                f"SGPPRB decision hash mismatch for {key[0]}:{key[1]}"
            )
        decisions.append(decision)
    decision_tuple = tuple(decisions)
    if len(decision_tuple) != 2 or _plan_id(decision_tuple) != claimed_plan:
        raise RuntimeError("SGPPRB decision set does not reproduce the frozen plan")

    membership = next(
        (
            item
            for item in decision_tuple
            if item.get("row_kind") == "membership"
            and item.get("row_id") == SGPPRB_MEMBERSHIP_ID
        ),
        None,
    )
    identity = next(
        (
            item
            for item in decision_tuple
            if item.get("row_kind") == "identity"
            and item.get("row_id") == SGPPRB_IDENTITY_ID
        ),
        None,
    )
    if membership is None or identity is None:
        raise RuntimeError("SGPPRB projection no longer contains the frozen membership/identity pair")
    if _as_int(membership.get("security_id"), field="membership.security_id") != SGPPRB_SECURITY_ID:
        raise RuntimeError("SGPPRB membership security changed")
    if _as_str(membership.get("cik"), field="membership.cik") != SGPPRB_CIK:
        raise RuntimeError("SGPPRB membership CIK changed")
    if security_symbol_key(
        _as_str(membership.get("symbol"), field="membership.symbol")
    ) != SGPPRB_SYMBOL:
        raise RuntimeError("SGPPRB membership symbol changed")
    if membership.get("status") != "reject_non_common_security":
        raise RuntimeError("membership 580 is no longer the exact rejection candidate")
    if membership.get("rejection_candidate") is not True:
        raise RuntimeError("membership 580 is not marked as a rejection candidate")
    if membership.get("evidence_id") != evidence.evidence_id:
        raise RuntimeError("membership 580 is not bound to the reconstructed SEC evidence")
    if identity.get("status") != "unresolved" or identity.get("rejection_candidate") is not False:
        raise RuntimeError("verified identity 1082 must remain fail-closed and unresolved")
    if identity.get("evidence_id") is not None:
        raise RuntimeError("verified identity 1082 must not inherit rejection evidence")

    discovery = _as_dict(payload.get("discovery"), field="discovery")
    if discovery.get("bridge_status") != "unique_sgpprb_identity":
        raise RuntimeError("SGPPRB projection no longer has one unique identity bridge")
    if discovery.get("issuer_matches_sec_evidence") is not True:
        raise RuntimeError("SGPPRB live issuer no longer matches the SEC evidence")
    if _as_int(
        discovery.get("overlapping_sgpprb_identity_count"),
        field="discovery.overlapping_sgpprb_identity_count",
    ) != 1:
        raise RuntimeError("SGPPRB overlapping identity count changed")
    overlapping = _as_list(
        discovery.get("overlapping_sgpprb_identities"),
        field="discovery.overlapping_sgpprb_identities",
    )
    bridge = _as_dict(overlapping[0], field="discovery.overlapping_sgpprb_identity")
    if _as_int(bridge.get("row_id"), field="bridge.row_id") != SGPPRB_IDENTITY_ID:
        raise RuntimeError("SGPPRB identity bridge row changed")
    if bridge.get("verification_status") != "verified":
        raise RuntimeError("identity 1082 is no longer verified; separate adjudication is required")

    start = date.fromisoformat(
        _as_str(membership.get("effective_from"), field="membership.effective_from")
    )
    raw_end = _as_optional_str(membership.get("effective_to"), field="membership.effective_to")
    return ValidatedSgpprbRejection(
        plan_id=claimed_plan,
        evidence=evidence,
        decision_hash=_as_str(
            membership.get("decision_hash"), field="membership.decision_hash"
        ),
        prior_source_hash=_as_str(
            membership.get("prior_source_hash"), field="membership.prior_source_hash"
        ),
        effective_from=start,
        effective_to=date.fromisoformat(raw_end) if raw_end else None,
    )


def rejected_membership_source(source: str) -> str:
    if source.endswith(SGPPRB_SOURCE_SUFFIX):
        return source
    combined = f"{source}{SGPPRB_SOURCE_SUFFIX}"
    if len(combined) > 128:
        raise RuntimeError("rejected membership source exceeds database limit")
    return combined


def rejected_membership_source_hash(
    rejection: ValidatedSgpprbRejection,
) -> str:
    return _digest(
        {
            "schema_version": SGPPRB_APPLY_SCHEMA_VERSION,
            "membership_row_id": SGPPRB_MEMBERSHIP_ID,
            "prior_source_hash": rejection.prior_source_hash,
            "projection_plan_id": rejection.plan_id,
            "decision_hash": rejection.decision_hash,
            "sec_evidence_id": rejection.evidence.evidence_id,
            "sec_payload_sha256": rejection.evidence.payload_sha256,
        }
    )
