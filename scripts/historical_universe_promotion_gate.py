"""Evaluate the final HU-2 promotion gate from measured production artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from fdre.research.historical_component_history import (
    HistoricalComponentHistoryAdapter,
    HistoricalComponentRecord,
)

_TARGET_START = date(2010, 1, 1)
_MIN_RESOLUTION = 0.95
_SCHEMA_VERSION = "fdre-hu2-final-promotion-gate-v1"


def _symbol(value: str) -> str:
    return value.strip().upper().replace(".", "-")


def _read(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _adjudicate_opposing_keys(
    remediation: dict[str, object],
    *,
    component_history: Path,
    component_history_ref: str,
) -> tuple[int, list[dict[str, object]]]:
    diagnostics = remediation.get("raw_evidence_diagnostics")
    if not isinstance(diagnostics, dict):
        raise ValueError("remediation artifact lacks raw_evidence_diagnostics")
    keys = diagnostics.get("same_date_symbol_opposing_event_keys")
    if not isinstance(keys, list):
        raise ValueError("remediation artifact lacks opposing-event keys")

    records = HistoricalComponentHistoryAdapter(
        source_ref=component_history_ref
    ).load(component_history)
    by_symbol: dict[str, list[HistoricalComponentRecord]] = {}
    for record in records:
        by_symbol.setdefault(_symbol(record.symbol), []).append(record)

    rows: list[dict[str, object]] = []
    unresolved = 0
    for raw in keys:
        if not isinstance(raw, dict):
            raise ValueError("invalid opposing-event row")
        symbol = _symbol(str(raw["raw_symbol"]))
        when = date.fromisoformat(str(raw["effective_at"]))
        matches = by_symbol.get(symbol, [])
        starts = sorted(
            {record.cik for record in matches if record.effective_from == when}
        )
        ends = sorted(
            {record.cik for record in matches if record.effective_to == when}
        )
        adjudicated = bool(starts and ends)
        if not adjudicated:
            unresolved += 1
        rows.append(
            {
                "effective_at": when.isoformat(),
                "symbol": symbol,
                "adjudicated": adjudicated,
                "incoming_ciks": starts,
                "outgoing_ciks": ends,
                "classification": (
                    "same-symbol constituent/security transition"
                    if adjudicated
                    else "unresolved"
                ),
            }
        )
    return unresolved, rows


def evaluate(
    *,
    coverage: dict[str, object],
    remediation: dict[str, object],
    anchor: dict[str, object],
    component_history: Path,
    component_history_ref: str,
) -> dict[str, object]:
    current = coverage.get("current_constituent_reconciliation")
    if not isinstance(current, dict):
        raise ValueError("coverage artifact lacks current reconciliation")
    target = remediation.get("target_window")
    if not isinstance(target, dict):
        raise ValueError("remediation artifact lacks target_window")

    missing_catalog = current.get("missing_catalog_symbols")
    missing_identity = current.get("missing_active_security_identity_symbols")
    ambiguous_identity = current.get("ambiguous_active_security_identity_symbols")
    if not isinstance(missing_catalog, list):
        raise ValueError("invalid missing_catalog_symbols")
    if not isinstance(missing_identity, list) or not isinstance(ambiguous_identity, list):
        raise ValueError("invalid current identity diagnostics")

    resolution_rate = float(target.get("security_resolution_rate", 0.0))
    unresolved_opposing, adjudications = _adjudicate_opposing_keys(
        remediation,
        component_history=component_history,
        component_history_ref=component_history_ref,
    )
    anchor_date = date.fromisoformat(str(anchor["effective_at"]))
    anchor_complete = bool(anchor.get("complete_target_window_anchor"))
    raw_anchor_count = anchor.get("constituent_count", 0)
    if isinstance(raw_anchor_count, bool) or not isinstance(raw_anchor_count, int):
        raise ValueError("anchor constituent_count must be an integer")
    anchor_count = raw_anchor_count
    anchor_met = anchor_complete and anchor_date <= _TARGET_START and 490 <= anchor_count <= 510
    replay = bool(coverage.get("deterministic_replay_match"))

    requirements: list[dict[str, object]] = [
        {
            "id": "current_constituent_catalog_complete",
            "actual": len(missing_catalog),
            "target": 0,
            "met": len(missing_catalog) == 0,
        },
        {
            "id": "current_constituent_security_identities_complete",
            "actual_missing": len(missing_identity),
            "actual_ambiguous": len(ambiguous_identity),
            "target_missing": 0,
            "target_ambiguous": 0,
            "met": not missing_identity and not ambiguous_identity,
        },
        {
            "id": "target_window_security_resolution_rate",
            "window_start": _TARGET_START.isoformat(),
            "actual": resolution_rate,
            "target_minimum": _MIN_RESOLUTION,
            "met": resolution_rate >= _MIN_RESOLUTION,
        },
        {
            "id": "opposing_raw_event_keys_adjudicated",
            "actual": unresolved_opposing,
            "target": 0,
            "met": unresolved_opposing == 0,
        },
        {
            "id": "complete_target_window_anchor",
            "actual": 1 if anchor_met else 0,
            "target_minimum": 1,
            "anchor_effective_at": anchor_date.isoformat(),
            "anchor_constituent_count": anchor_count,
            "met": anchor_met,
        },
        {
            "id": "deterministic_replay",
            "actual": replay,
            "target": True,
            "met": replay,
        },
    ]
    return {
        "schema_version": _SCHEMA_VERSION,
        "audit_id": coverage.get("audit_id"),
        "promotion_gate_met": all(bool(item["met"]) for item in requirements),
        "requirements": requirements,
        "opposing_event_adjudications": adjudications,
        "interpretation": (
            "The 95% identity threshold is a readiness floor, not a claim that every historical "
            "membership interval is verified. HU-3 strict mode must continue to fail closed on "
            "provisional membership or identity rows."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate the final HU-2 promotion gate.")
    parser.add_argument("--coverage", required=True, type=Path)
    parser.add_argument("--remediation", required=True, type=Path)
    parser.add_argument("--anchor", required=True, type=Path)
    parser.add_argument("--component-history", required=True, type=Path)
    parser.add_argument("--component-history-ref", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="Return non-zero when the measured promotion gate is not satisfied.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = evaluate(
        coverage=_read(args.coverage),
        remediation=_read(args.remediation),
        anchor=_read(args.anchor),
        component_history=args.component_history,
        component_history_ref=args.component_history_ref,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.require_pass and not payload["promotion_gate_met"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
