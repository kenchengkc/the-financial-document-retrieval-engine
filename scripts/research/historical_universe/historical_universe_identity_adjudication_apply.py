"""Commit the exact HU-5 identity plan only after both production gates close."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from fdre.research.historical_universe_identity_adjudication import (
    EXPECTED_ACTION_COUNTS,
    EXPECTED_IDENTITY_ADJUDICATION_MANIFEST_ID,
    EXPECTED_IDENTITY_ADJUDICATION_PLAN_ID,
    EXPECTED_RESIDUAL_SEC_PLAN_ID,
    EXPECTED_TOPOLOGY_AUDIT_ID,
    EXPECTED_TOPOLOGY_ID,
)
from fdre.research.historical_universe_identity_adjudication_apply import (
    IDENTITY_ADJUDICATION_APPLY_SCHEMA_VERSION,
    validate_identity_adjudication_projection,
)
from fdre.research.historical_universe_identity_adjudication_manifest import (
    build_hu5_identity_adjudication_cases,
)
from scripts.research.historical_universe.historical_universe_identity_adjudication_projection import (  # noqa: E501
    UNIVERSE_CODE,
    WINDOW_END,
    WINDOW_START,
    _current_gate,
    _current_identity_audit,
    _gate_payload,
    _require_pre_state,
    _topology_payload,
    require_closed_post_state,
    stage_identity_actions,
)
from scripts.research.historical_universe.historical_universe_identity_topology import (
    build_live_residual_identity_topology,
)

FROZEN_PROJECTION_RUN_ID = 33908491559
FROZEN_PROJECTION_ARTIFACT_ID = 9950441480
FROZEN_PROJECTION_ARTIFACT_DIGEST = (
    "sha256:26595955dc6799e72bac5a6aec8e9ec7ac5f7f2d1d000665da0405c533da05ee"
)
EXPECTED_POST_GATE_ID = "95d53555924f4e60f929ad9377f188a70aba808f82697cf8c9b437aa047463b8"
EXPECTED_POST_PROVENANCE_ID = "0662048623bc4a3dc0572ee56a3896de3d2ae6aea0ddaa34227bdd755e27c256"


def _validate_request(
    *,
    apply: bool,
    allow_prod: bool,
    expected_manifest_id: str,
    expected_plan_id: str,
    expected_audit_id: str,
    expected_topology_id: str,
) -> None:
    if not apply or not allow_prod:
        raise RuntimeError("identity apply requires --apply and FDRE_ALLOW_PROD=1")
    supplied = (expected_manifest_id, expected_plan_id, expected_audit_id, expected_topology_id)
    expected = (
        EXPECTED_IDENTITY_ADJUDICATION_MANIFEST_ID,
        EXPECTED_IDENTITY_ADJUDICATION_PLAN_ID,
        EXPECTED_TOPOLOGY_AUDIT_ID,
        EXPECTED_TOPOLOGY_ID,
    )
    if supplied != expected:
        raise RuntimeError("identity apply inputs differ from frozen reviewed IDs")


def _lock_inputs(session: Session) -> None:
    """Prevent concurrent writes and inserts from invalidating the checked snapshot."""
    if session.get_bind().dialect.name != "postgresql":
        raise RuntimeError("production identity apply requires PostgreSQL")
    session.execute(text("SET LOCAL lock_timeout = '15s'"))
    session.execute(text("SET LOCAL statement_timeout = '120s'"))
    session.execute(text("SET LOCAL idle_in_transaction_session_timeout = '180s'"))
    session.execute(
        text(
            "LOCK TABLE companies, securities, security_identity_periods, "
            "universe_memberships, security_identity_evidence IN SHARE ROW EXCLUSIVE MODE"
        )
    )


def apply_identity_adjudication(
    session: Session,
    *,
    residual_sec: dict[str, Any],
    projection: dict[str, Any],
) -> dict[str, object]:
    """Own one transaction, revalidate all inputs, stage, check, then commit."""
    with session.begin():
        _lock_inputs(session)
        topology, audit_before = build_live_residual_identity_topology(
            session,
            universe_code=UNIVERSE_CODE,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            expected_audit_id=EXPECTED_TOPOLOGY_AUDIT_ID,
        )
        cases = build_hu5_identity_adjudication_cases(
            topology=_topology_payload(topology, audit_before),
            residual_sec=residual_sec,
        )
        validate_identity_adjudication_projection(
            projection,
            expected_plan_id=EXPECTED_IDENTITY_ADJUDICATION_PLAN_ID,
            cases=cases,
        )
        gate_before = _current_gate(session)
        _require_pre_state(gate_before, audit_before)
        if _gate_payload(gate_before) != projection.get("strict_coverage_before"):
            raise RuntimeError("live merged gate differs from frozen projection pre-state")
        if audit_before.as_dict() != projection.get("identity_strict_coverage_before"):
            raise RuntimeError("live identity audit differs from frozen projection pre-state")

        changes = stage_identity_actions(
            session,
            cases,
            manifest_id=EXPECTED_IDENTITY_ADJUDICATION_MANIFEST_ID,
            plan_id=EXPECTED_IDENTITY_ADJUDICATION_PLAN_ID,
            projection=False,
        )
        if len(changes) != 45:
            raise RuntimeError("identity apply did not stage exactly 45 actions")
        gate_after = _current_gate(session)
        audit_after = _current_identity_audit(session)
        require_closed_post_state(gate_after, audit_after)
        if _gate_payload(gate_after) != projection.get("strict_coverage_projected"):
            raise RuntimeError("live post-state differs from the frozen projected merged gate")
        if (
            gate_after.gate_manifest_id != EXPECTED_POST_GATE_ID
            or gate_after.input_provenance_id != EXPECTED_POST_PROVENANCE_ID
        ):
            raise RuntimeError("live post-state gate provenance differs from frozen projection")

        # Audit IDs include inserted database row IDs; the projection used negative IDs.
        # The merged gate fingerprints semantic row contents, so it must match exactly.
        result: dict[str, object] = {
            "schema_version": IDENTITY_ADJUDICATION_APPLY_SCHEMA_VERSION,
            "mode": "apply",
            "applied": True,
            "transaction_committed": True,
            "manifest_id": EXPECTED_IDENTITY_ADJUDICATION_MANIFEST_ID,
            "plan_id": EXPECTED_IDENTITY_ADJUDICATION_PLAN_ID,
            "frozen_audit_id": EXPECTED_TOPOLOGY_AUDIT_ID,
            "frozen_topology_id": EXPECTED_TOPOLOGY_ID,
            "frozen_residual_sec_plan_id": EXPECTED_RESIDUAL_SEC_PLAN_ID,
            "projection_run_id": FROZEN_PROJECTION_RUN_ID,
            "projection_artifact_id": FROZEN_PROJECTION_ARTIFACT_ID,
            "projection_artifact_digest": FROZEN_PROJECTION_ARTIFACT_DIGEST,
            "action_count": len(changes),
            "action_counts": EXPECTED_ACTION_COUNTS,
            "decisions": projection["decisions"],
            "reviewed_evidence": projection["reviewed_evidence"],
            "changes": changes,
            "strict_coverage_before": _gate_payload(gate_before),
            "strict_coverage_after": _gate_payload(gate_after),
            "identity_strict_coverage_before": audit_before.as_dict(),
            "identity_strict_coverage_after": audit_after.as_dict(),
        }
        # Check serializability before committing; no artifact is emitted on rollback.
        json.dumps(result, sort_keys=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--residual-sec", type=Path, required=True)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--expected-manifest-id", required=True)
    parser.add_argument("--expected-plan-id", required=True)
    parser.add_argument("--expected-audit-id", required=True)
    parser.add_argument("--expected-topology-id", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _validate_request(
        apply=args.apply,
        allow_prod=os.environ.get("FDRE_ALLOW_PROD") == "1",
        expected_manifest_id=args.expected_manifest_id,
        expected_plan_id=args.expected_plan_id,
        expected_audit_id=args.expected_audit_id,
        expected_topology_id=args.expected_topology_id,
    )
    residual_sec = json.loads(args.residual_sec.read_text(encoding="utf-8"))
    projection = json.loads(args.projection.read_text(encoding="utf-8"))
    if not isinstance(residual_sec, dict) or not isinstance(projection, dict):
        raise RuntimeError("frozen artifact roots must be objects")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            result = apply_identity_adjudication(
                session, residual_sec=residual_sec, projection=projection
            )
    finally:
        engine.dispose()
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "applied",
                    "transaction_committed",
                    "manifest_id",
                    "plan_id",
                    "action_counts",
                    "strict_coverage_after",
                )
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
