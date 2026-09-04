"""Provenance helpers shared by final HU-5 identity projection and production apply."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from fdre.research.historical_universe_identity_adjudication import (
    IdentityAdjudicationCase,
)

IDENTITY_ADJUDICATION_APPLY_SCHEMA_VERSION = "fdre-hu5-final-identity-adjudication-apply-v1"
REVIEWED_SOURCE_OBSERVED_AT = datetime(2026, 9, 4, 6, 40, tzinfo=timezone.utc)
APPLIED_SOURCE_SUFFIX = "hu5-final-identity-adjudication"


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def applied_identity_source_hash(
    case: IdentityAdjudicationCase,
    *,
    manifest_id: str,
    plan_id: str,
) -> str:
    return _hash(
        {
            "schema_version": IDENTITY_ADJUDICATION_APPLY_SCHEMA_VERSION,
            "manifest_id": manifest_id,
            "plan_id": plan_id,
            "case_id": case.case_id,
            "decision_hash": case.decision_hash,
            "action": case.action,
            "security_id": case.security_id,
            "cik": case.cik,
            "symbol": case.symbol,
            "prior_source_hash": case.prior_source_hash,
            "target_effective_from": case.target_effective_from.isoformat(),
            "target_effective_to": (
                case.target_effective_to.isoformat() if case.target_effective_to else None
            ),
            "evidence_ids": sorted(item.evidence_id for item in case.evidence),
        }
    )
