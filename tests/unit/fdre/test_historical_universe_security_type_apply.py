from __future__ import annotations

from datetime import date
from typing import cast

import pytest

from fdre.research.historical_universe_security_type import (
    SecSecurityTypeEvidence,
    SecurityTypeAdjudicationTarget,
    extract_schering_plough_preferred_evidence,
    plan_security_type_adjudication,
    security_type_plan_id,
)
from fdre.research.historical_universe_security_type_apply import (
    SGPPRB_PROJECTION_SCHEMA_VERSION,
    rejected_membership_source,
    rejected_membership_source_hash,
    validate_sgpprb_projection,
)

SEC_URL = (
    "https://www.sec.gov/Archives/edgar/data/310158/000095012307011295/y37189bte424b2.htm"
)


def _evidence() -> SecSecurityTypeEvidence:
    return extract_schering_plough_preferred_evidence(
        b"""
        <html><body>
        Schering-Plough is offering shares of 6.00% mandatory convertible preferred stock,
        referred to as the 2007 Preferred Stock.
        The 2007 Preferred Stock has been approved for listing on the New York Stock Exchange,
        subject to issuance, under the symbol SGP PrB.
        Schering-Plough's common shares are listed on the New York Stock Exchange under the
        symbol SGP.
        </body></html>
        """,
        source_url=SEC_URL,
    )


def _payload() -> tuple[dict[str, object], str]:
    evidence = _evidence()
    identity = SecurityTypeAdjudicationTarget(
        row_kind="identity",
        row_id=1082,
        security_id=798,
        cik="0000310158",
        symbol="SGPPRB",
        effective_from=date(2009, 12, 31),
        effective_to=date(2010, 1, 23),
        prior_source_hash="b" * 64,
        verification_status="verified",
    )
    membership = SecurityTypeAdjudicationTarget(
        row_kind="membership",
        row_id=580,
        security_id=798,
        cik="0000310158",
        symbol="SGPPRB",
        effective_from=date(2009, 12, 31),
        effective_to=date(2010, 1, 22),
        prior_source_hash="a" * 64,
        verification_status="provisional",
    )
    decisions = plan_security_type_adjudication((identity, membership), evidence)
    plan_id = security_type_plan_id(decisions)
    payload: dict[str, object] = {
        "schema_version": SGPPRB_PROJECTION_SCHEMA_VERSION,
        "mode": "projection",
        "applied": False,
        "plan_id": plan_id,
        "known_blocker_membership_id": 580,
        "target_sec_cik": "0000310158",
        "target_symbol": "SGPPRB",
        "sec_evidence": evidence.as_dict(),
        "discovery": {
            "bridge_status": "unique_sgpprb_identity",
            "issuer_matches_sec_evidence": True,
            "overlapping_sgpprb_identity_count": 1,
            "overlapping_sgpprb_identities": [
                {
                    "row_id": 1082,
                    "security_id": 798,
                    "symbol": "SGPPRB",
                    "verification_status": "verified",
                }
            ],
        },
        "target_count": 2,
        "rejection_candidate_count": 1,
        "staged_rejection_count": 1,
        "decisions": [item.as_dict() for item in decisions],
    }
    return payload, plan_id


def test_validates_exact_frozen_shape() -> None:
    payload, plan_id = _payload()

    rejection = validate_sgpprb_projection(payload, expected_plan_id=plan_id)

    assert rejection.plan_id == plan_id
    assert rejection.evidence.security_type == "preferred_stock"
    assert rejection.prior_source_hash == "a" * 64
    assert rejection.effective_from == date(2009, 12, 31)
    assert rejection.effective_to == date(2010, 1, 22)


def test_rejects_plan_drift() -> None:
    payload, _ = _payload()

    with pytest.raises(RuntimeError, match="plan drift"):
        validate_sgpprb_projection(payload, expected_plan_id="0" * 64)


def test_rejects_tampered_sec_evidence() -> None:
    payload, plan_id = _payload()
    evidence = dict(cast(dict[str, object], payload["sec_evidence"]))
    evidence["payload_sha256"] = "0" * 64
    payload["sec_evidence"] = evidence

    with pytest.raises(RuntimeError, match="evidence hash mismatch"):
        validate_sgpprb_projection(payload, expected_plan_id=plan_id)


def test_rejects_attempt_to_reject_verified_identity() -> None:
    payload, plan_id = _payload()
    raw_decisions = cast(list[dict[str, object]], payload["decisions"])
    decisions = [dict(item) for item in raw_decisions]
    identity = next(item for item in decisions if item["row_kind"] == "identity")
    identity["status"] = "reject_non_common_security"
    identity["rejection_candidate"] = True
    payload["decisions"] = decisions

    with pytest.raises(RuntimeError, match="decision hash mismatch"):
        validate_sgpprb_projection(payload, expected_plan_id=plan_id)


def test_rejects_missing_unique_verified_bridge() -> None:
    payload, plan_id = _payload()
    discovery = dict(cast(dict[str, object], payload["discovery"]))
    discovery["bridge_status"] = "ambiguous_overlapping_sgpprb_identities"
    payload["discovery"] = discovery

    with pytest.raises(RuntimeError, match="unique identity bridge"):
        validate_sgpprb_projection(payload, expected_plan_id=plan_id)


def test_rejection_source_hash_is_deterministic_and_evidence_bound() -> None:
    payload, plan_id = _payload()
    rejection = validate_sgpprb_projection(payload, expected_plan_id=plan_id)

    assert rejected_membership_source("fja05680/sp500") == (
        "fja05680/sp500+sec/noncommon-reject"
    )
    assert rejected_membership_source_hash(rejection) == rejected_membership_source_hash(
        rejection
    )
    assert len(rejected_membership_source_hash(rejection)) == 64
