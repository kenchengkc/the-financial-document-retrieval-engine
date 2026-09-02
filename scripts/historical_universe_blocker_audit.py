from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from fdre.research.hu5_blockers import (
    build_hu5_strict_blocker_audit,
    write_hu5_strict_blocker_audit,
)
from fdre.research.hu5_universe import (
    hu5_universe_input_provenance_id,
    load_hu5_universe_records,
)

DEFAULT_START = date(2010, 1, 1)
DEFAULT_END = date(2026, 9, 1)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Attribute provisional Historical Universe blockers across the HU-5 window."
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--universe-code", default="sp500")
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            records = load_hu5_universe_records(
                session,
                universe_code=args.universe_code,
                window_start=args.start,
                window_end=args.end,
            )
    finally:
        engine.dispose()

    provenance_id = hu5_universe_input_provenance_id(records)
    audit = build_hu5_strict_blocker_audit(
        records,
        universe_code=args.universe_code,
        input_provenance_id=provenance_id,
        window_start=args.start,
        window_end=args.end,
    )
    write_hu5_strict_blocker_audit(args.output, audit)
    summary = {
        "blocker_audit_id": audit.blocker_audit_id,
        "membership_blocker_count": audit.membership_blocker_count,
        "latent_identity_blocker_count": audit.latent_identity_blocker_count,
        "membership_blocked_day_count": audit.membership_blocked_day_count,
        "membership_unblocked_day_count": audit.membership_unblocked_day_count,
        "projected_strict_day_count_after_membership_only": (
            audit.projected_strict_day_count_after_membership_only
        ),
        "minimum_active_membership_blockers": audit.minimum_active_membership_blockers,
        "maximum_active_membership_blockers": audit.maximum_active_membership_blockers,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
