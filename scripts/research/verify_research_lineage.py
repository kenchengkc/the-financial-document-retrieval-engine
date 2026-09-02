from __future__ import annotations

import argparse
import json
from pathlib import Path

from fdre.research.signal_study import SignalStudyReport
from fdre.research.verification import (
    verify_research_panel_export,
    verify_signal_study_lineage,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify FDRE point-in-time research lineage artifacts."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    panel = subparsers.add_parser("panel", help="Verify a panel JSON/CSV/Parquet export")
    panel.add_argument("path", type=Path)

    signal = subparsers.add_parser("signal", help="Verify a saved signal-study JSON report")
    signal.add_argument("path", type=Path)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.command == "panel":
        verified_rows = verify_research_panel_export(args.path)
        print(f"verified panel lineage: {verified_rows} rows")
        return

    payload = json.loads(args.path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "report" in payload:
        payload = payload["report"]
    report = SignalStudyReport.model_validate(payload)
    verify_signal_study_lineage(report)
    print(
        "verified signal lineage: "
        f"{len(report.feature_lineage_by_accession)} feature inputs"
    )


if __name__ == "__main__":
    main()
