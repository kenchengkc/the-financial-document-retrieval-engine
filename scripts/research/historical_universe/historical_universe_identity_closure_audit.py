"""Independently read committed HU-5 identity closure and compare apply provenance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from fdre.research.historical_universe_identity_adjudication import (
    EXPECTED_IDENTITY_ADJUDICATION_MANIFEST_ID,
    EXPECTED_IDENTITY_ADJUDICATION_PLAN_ID,
)
from scripts.research.historical_universe.historical_universe_identity_adjudication_apply import (
    EXPECTED_POST_GATE_ID,
    EXPECTED_POST_PROVENANCE_ID,
)
from scripts.research.historical_universe.historical_universe_identity_adjudication_projection import (  # noqa: E501
    _current_gate,
    _current_identity_audit,
    _gate_payload,
    require_closed_post_state,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--apply-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    applied = json.loads(args.apply_report.read_text(encoding="utf-8"))
    if (
        applied.get("applied") is not True
        or applied.get("transaction_committed") is not True
        or applied.get("manifest_id") != EXPECTED_IDENTITY_ADJUDICATION_MANIFEST_ID
        or applied.get("plan_id") != EXPECTED_IDENTITY_ADJUDICATION_PLAN_ID
    ):
        raise RuntimeError("apply report does not represent the committed reviewed plan")
    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            if engine.dialect.name == "postgresql":
                session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            gate = _current_gate(session)
            audit = _current_identity_audit(session)
            require_closed_post_state(gate, audit)
            if (
                gate.gate_manifest_id != EXPECTED_POST_GATE_ID
                or gate.input_provenance_id != EXPECTED_POST_PROVENANCE_ID
                or _gate_payload(gate) != applied.get("strict_coverage_after")
                or audit.as_dict() != applied.get("identity_strict_coverage_after")
            ):
                raise RuntimeError("independent committed-state audit differs from apply report")
            session.rollback()
    finally:
        engine.dispose()
    result = {
        "schema_version": "fdre-hu5-final-identity-closure-audit-v1",
        "mode": "independent_read_only_audit",
        "manifest_id": EXPECTED_IDENTITY_ADJUDICATION_MANIFEST_ID,
        "plan_id": EXPECTED_IDENTITY_ADJUDICATION_PLAN_ID,
        "strict_coverage": _gate_payload(gate),
        "identity_strict_coverage": audit.as_dict(),
        "matches_committed_apply_report": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"strict_coverage": _gate_payload(gate), "audit_id": audit.audit_id}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
