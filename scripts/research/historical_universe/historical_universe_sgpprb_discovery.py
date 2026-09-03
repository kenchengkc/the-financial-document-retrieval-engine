"""Read-only production snapshot for the known SGPPRB HU blocker.

This runner snapshots ORM-backed discovery fields before rolling back any staged adjudication so
production topology can be inspected without persisting a change.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from scripts.research.historical_universe.historical_universe_security_type_projection import (
    BLOCKER_MEMBERSHIP_ID,
    PROJECTION_SCHEMA_VERSION,
    TARGET_CIK,
    TARGET_SYMBOL,
    _adjudication_targets,
    _date,
    _identity_dict,
    _membership_dict,
    _stage_rejections,
    discover_sgpprb_blocker,
    fetch_sec_security_type_evidence,
)
from fdre.research.historical_universe_identity import normalize_cik
from fdre.research.historical_universe_security_type import (
    plan_security_type_adjudication,
    security_type_plan_id,
)
from fdre.research.hu5_universe import build_hu5_universe_gate, load_hu5_universe_records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only live SGPPRB blocker discovery.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--window-start", type=_date, default=date(2010, 1, 1))
    parser.add_argument("--window-end", type=_date, default=date(2026, 9, 1))
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.window_end < args.window_start:
        raise RuntimeError("window end must not precede window start")

    evidence = fetch_sec_security_type_evidence(
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/310158/"
            "000095012307011295/y37189bte424b2.htm"
        )
    )
    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            membership, security, company, identities, overlapping = discover_sgpprb_blocker(
                session
            )
            issuer_cik = normalize_cik(company.cik)

            membership_snapshot = _membership_dict(membership)
            security_snapshot = {
                "security_id": security.id,
                "company_id": security.company_id,
                "security_type": security.security_type,
                "share_class": security.share_class,
            }
            company_snapshot = {
                "company_id": company.id,
                "cik": issuer_cik,
                "ticker": company.ticker,
                "name": company.name,
            }
            identity_snapshots = [_identity_dict(row) for row in identities]
            overlapping_snapshots = [_identity_dict(row) for row in overlapping]

            if len(overlapping) == 1:
                bridge_status = "unique_sgpprb_identity"
            elif not overlapping:
                bridge_status = "no_overlapping_sgpprb_identity"
            else:
                bridge_status = "ambiguous_overlapping_sgpprb_identities"

            targets = _adjudication_targets(
                membership,
                overlapping,
                issuer_cik=issuer_cik,
            )
            decisions = plan_security_type_adjudication(targets, evidence)
            rejection_count = sum(item.rejection_candidate for item in decisions)
            plan_id = security_type_plan_id(decisions)
            status_counts = Counter(item.status for item in decisions)

            before_records = load_hu5_universe_records(
                session,
                universe_code="sp500",
                window_start=args.window_start,
                window_end=args.window_end,
            )
            before_gate = build_hu5_universe_gate(
                before_records,
                universe_code="sp500",
                window_start=args.window_start,
                window_end=args.window_end,
            )

            staged_count = _stage_rejections(session, decisions)
            after_records = load_hu5_universe_records(
                session,
                universe_code="sp500",
                window_start=args.window_start,
                window_end=args.window_end,
            )
            after_gate = build_hu5_universe_gate(
                after_records,
                universe_code="sp500",
                window_start=args.window_start,
                window_end=args.window_end,
            )

            payload = {
                "schema_version": PROJECTION_SCHEMA_VERSION,
                "mode": "projection",
                "applied": False,
                "plan_id": plan_id,
                "known_blocker_membership_id": BLOCKER_MEMBERSHIP_ID,
                "target_sec_cik": TARGET_CIK,
                "target_symbol": TARGET_SYMBOL,
                "sec_evidence": evidence.as_dict(),
                "discovery": {
                    "membership": membership_snapshot,
                    "security": security_snapshot,
                    "company": company_snapshot,
                    "identity_periods": identity_snapshots,
                    "overlapping_sgpprb_identity_count": len(overlapping_snapshots),
                    "overlapping_sgpprb_identities": overlapping_snapshots,
                    "bridge_status": bridge_status,
                    "issuer_matches_sec_evidence": issuer_cik == evidence.cik,
                },
                "target_count": len(targets),
                "rejection_candidate_count": rejection_count,
                "staged_rejection_count": staged_count,
                "status_counts": dict(sorted(status_counts.items())),
                "decisions": [item.as_dict() for item in decisions],
                "strict_coverage_before": {
                    "gate_manifest_id": before_gate.gate_manifest_id,
                    "input_provenance_id": before_gate.input_provenance_id,
                    "strict_eligible_day_count": before_gate.strict_eligible_day_count,
                    "invalid_day_count": before_gate.invalid_day_count,
                    "day_count": before_gate.day_count,
                },
                "strict_coverage_projected": {
                    "gate_manifest_id": after_gate.gate_manifest_id,
                    "input_provenance_id": after_gate.input_provenance_id,
                    "strict_eligible_day_count": after_gate.strict_eligible_day_count,
                    "invalid_day_count": after_gate.invalid_day_count,
                    "day_count": after_gate.day_count,
                },
                "interpretation": (
                    "Read-only production discovery anchored on blocker membership 580. Live ORM "
                    "state was snapshotted before any staged adjudication was rolled back."
                ),
            }
            session.rollback()
    finally:
        engine.dispose()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "plan_id": payload["plan_id"],
                "membership": payload["discovery"]["membership"],
                "security": payload["discovery"]["security"],
                "company": payload["discovery"]["company"],
                "bridge_status": payload["discovery"]["bridge_status"],
                "overlapping_sgpprb_identities": payload["discovery"][
                    "overlapping_sgpprb_identities"
                ],
                "rejection_candidate_count": payload["rejection_candidate_count"],
                "strict_eligible_days_before": payload["strict_coverage_before"][
                    "strict_eligible_day_count"
                ],
                "strict_eligible_days_projected": payload["strict_coverage_projected"][
                    "strict_eligible_day_count"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
