"""Apply the exact SEC-backed rejection of SGPPRB membership row 580."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models.historical_universe import UniverseMembership
from fdre.research.historical_universe_security_type_apply import (
    SGPPRB_APPLY_SCHEMA_VERSION,
    SGPPRB_MEMBERSHIP_ID,
    SGPPRB_SECURITY_ID,
    ValidatedSgpprbRejection,
    rejected_membership_source,
    rejected_membership_source_hash,
    validate_sgpprb_projection,
)


def _validate_apply_request(*, apply: bool, expected_plan_id: str, allow_prod: bool) -> None:
    if not apply:
        raise RuntimeError("SGPPRB rejection apply requires explicit --apply")
    if not allow_prod:
        raise RuntimeError("--apply requires FDRE_ALLOW_PROD=1")
    if len(expected_plan_id) != 64:
        raise RuntimeError("--expected-plan-id must be a SHA-256 plan id")


def _assert_live_membership(
    session: Session,
    rejection: ValidatedSgpprbRejection,
) -> UniverseMembership:
    row = session.get(UniverseMembership, SGPPRB_MEMBERSHIP_ID)
    if row is None:
        raise RuntimeError(f"membership row {SGPPRB_MEMBERSHIP_ID} no longer exists")
    if row.universe_code != "sp500":
        raise RuntimeError(f"membership row {SGPPRB_MEMBERSHIP_ID} universe changed")
    if row.security_id != SGPPRB_SECURITY_ID:
        raise RuntimeError(f"membership row {SGPPRB_MEMBERSHIP_ID} security changed")
    if row.effective_from != rejection.effective_from or row.effective_to != rejection.effective_to:
        raise RuntimeError(f"membership row {SGPPRB_MEMBERSHIP_ID} interval changed")
    if row.source_hash != rejection.prior_source_hash:
        raise RuntimeError(f"membership row {SGPPRB_MEMBERSHIP_ID} source hash changed")
    if row.verification_status != "provisional":
        raise RuntimeError(f"membership row {SGPPRB_MEMBERSHIP_ID} is no longer provisional")
    return row


def _stage_rejection(
    session: Session,
    rejection: ValidatedSgpprbRejection,
) -> dict[str, object]:
    row = _assert_live_membership(session, rejection)
    prior_source = row.source
    prior_source_hash = row.source_hash
    row.source = rejected_membership_source(row.source)
    row.source_hash = rejected_membership_source_hash(rejection)
    row.verification_status = "rejected"
    row.confidence = max(float(row.confidence), 0.99)
    session.flush()
    return {
        "row_id": row.id,
        "security_id": row.security_id,
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "prior_source": prior_source,
        "source": row.source,
        "prior_source_hash": prior_source_hash,
        "source_hash": row.source_hash,
        "verification_status": row.verification_status,
        "confidence": float(row.confidence),
        "decision_hash": rejection.decision_hash,
        "sec_evidence_id": rejection.evidence.evidence_id,
        "sec_payload_sha256": rejection.evidence.payload_sha256,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply the exact SEC-backed SGPPRB membership rejection."
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--projection", required=True, type=Path)
    parser.add_argument("--expected-plan-id", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    _validate_apply_request(
        apply=args.apply,
        expected_plan_id=args.expected_plan_id,
        allow_prod=os.environ.get("FDRE_ALLOW_PROD") == "1",
    )
    raw_payload: Any = json.loads(args.projection.read_text(encoding="utf-8"))
    if not isinstance(raw_payload, dict):
        raise RuntimeError("SGPPRB projection root must be an object")
    rejection = validate_sgpprb_projection(
        raw_payload,
        expected_plan_id=args.expected_plan_id,
    )

    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            row_result = _stage_rejection(session, rejection)
            session.commit()
    finally:
        engine.dispose()

    result = {
        "schema_version": SGPPRB_APPLY_SCHEMA_VERSION,
        "mode": "apply",
        "applied": True,
        "plan_id": rejection.plan_id,
        "applied_membership_rejections": 1,
        "row": row_result,
        "interpretation": (
            "Rejected only S&P 500 membership row 580 after a freshly replayed projection "
            "reproduced the frozen plan, immutable SEC preferred-stock evidence, unique verified "
            "SGPPRB identity bridge, and exact live provisional row/source hash. Verified identity "
            "row 1082 and security row 798 were not modified."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "plan_id": rejection.plan_id,
                "applied_membership_rejections": 1,
                "row_id": SGPPRB_MEMBERSHIP_ID,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
