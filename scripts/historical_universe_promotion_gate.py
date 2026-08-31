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
_SCHEMA_VERSION = "fdre-hu2-final-promotion-gate-v4"

_OPPOSING_EVENT_ADJUDICATIONS: dict[
    tuple[str, date], tuple[tuple[str, ...], tuple[str, ...]]
] = {
    ("AET", date(2000, 12, 13)): (("0001013761",), ("0001122304",)),
    ("GAS", date(2011, 12, 12)): (("0000072020",), ("0001004155",)),
    ("JCI", date(2016, 9, 2)): (("0000053669",), ("0000833444",)),
    ("FOX", date(2019, 3, 19)): (("0001308161",), ("0001754301",)),
    ("FOXA", date(2019, 3, 19)): (("0001308161",), ("0001754301",)),
}


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
        ends, starts = _OPPOSING_EVENT_ADJUDICATIONS.get(
            (symbol, when),
            (
                tuple(sorted({record.cik for record in matches if record.effective_to == when})),
                tuple(sorted({record.cik for record in matches if record.effective_from == when})),
            ),
        )
        adjudicated = bool(starts and ends)
        if not adjudicated:
            unresolved += 1
        rows.append(
            {
                "effective_at": when.isoformat(),
                "symbol": symbol,
                "adjudicated": adjudicated,
                "incoming_ciks": list(starts),
                "outgoing_ciks": list(ends),
                "classification": (
                    "same-symbol constituent/security transition"
                    if adjudicated
                    else "unresolved"
                ),
                "identity_evidence_refs": [
                    *(f"https://data.sec.gov/submissions/CIK{cik}.json" for cik in ends),
                    *(f"https://data.sec.gov/submissions/CIK{cik}.json" for cik in starts),
                ],
            }
        )
    return unresolved, rows


def evaluate(
    *,
    coverage: dict[str, object],
    remediation: dict[str, object],
    anchor: dict[str, object],
    anchor_reconciliation: dict[str, object],
    boundary_audit: dict[str, object],
    materialization: dict[str, object],
    component_cik_audit: dict[str, object] | None = None,
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

    raw_resolution_rate = (component_cik_audit or {}).get(
        "projected_resolution_rate",
        target.get("security_resolution_rate", 0.0),
    )
    if isinstance(raw_resolution_rate, bool) or not isinstance(
        raw_resolution_rate, (int, float)
    ):
        raise ValueError("target-window resolution rate must be numeric")
    resolution_rate = float(raw_resolution_rate)
    residual_count = (component_cik_audit or {}).get("residual_count")
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
    anchor_reconciled = anchor_reconciliation.get("anchor_reconciled") is True
    anchor_identity_ready = anchor_reconciliation.get("production_identity_ready") is True
    identity_safe_anchor = anchor_reconciliation.get("identity_safe_anchor")
    if not isinstance(identity_safe_anchor, dict):
        identity_safe_anchor = {}
    identity_anchor_date = date.fromisoformat(
        str(identity_safe_anchor.get("effective_at", anchor_date.isoformat()))
    )
    identity_anchor_count = identity_safe_anchor.get("constituent_count", 0)
    identity_anchor_id = identity_safe_anchor.get("anchor_id")
    raw_boundary_count = boundary_audit.get("interval_count")
    raw_boundary_rows = boundary_audit.get("intervals")
    raw_status_counts = boundary_audit.get("status_counts")
    if isinstance(raw_boundary_count, bool) or not isinstance(raw_boundary_count, int):
        raise ValueError("boundary audit interval_count must be an integer")
    if not isinstance(raw_boundary_rows, list) or not isinstance(raw_status_counts, dict):
        raise ValueError("boundary audit lacks interval decisions/status counts")
    classified_boundary_count = sum(
        value
        for value in raw_status_counts.values()
        if isinstance(value, int) and not isinstance(value, bool)
    )
    boundary_adjudication_complete = (
        raw_boundary_count == len(raw_boundary_rows) == classified_boundary_count
    )
    boundaries_production_ready = boundary_audit.get("production_apply_eligible") is True
    replay = coverage.get("deterministic_replay_match") is True
    validation = materialization.get("validation")
    if not isinstance(validation, dict):
        raise ValueError("materialization artifact lacks validation")
    materialization_applied = materialization.get("applied") is True
    commit_eligible = validation.get("commit_eligible") is True
    provisional_anchor_match = validation.get("provisional_anchor_match") is True
    strict_anchor_match = validation.get("strict_anchor_match") is True
    materialized_replay = validation.get("deterministic_replay_match") is True
    interval_counts = {
        "identity_overlap_count": validation.get("identity_overlap_count"),
        "membership_overlap_count": validation.get("membership_overlap_count"),
        "missing_identity_coverage_count": validation.get("missing_identity_coverage_count"),
    }
    interval_integrity = all(
        isinstance(value, int) and not isinstance(value, bool) and value == 0
        for value in interval_counts.values()
    )
    materialization_anchor_aligned = (
        validation.get("anchor_id") == identity_anchor_id
        and validation.get("universe_code")
        == identity_safe_anchor.get("universe_code", "sp500")
        and validation.get("as_of") == identity_anchor_date.isoformat()
        and validation.get("expected_constituent_count") == identity_anchor_count
    )

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
            "residual_observation_count": residual_count,
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
            "id": "anchor_symbol_discrepancies_reconciled",
            "actual": anchor_reconciled,
            "target": True,
            "met": anchor_reconciled,
        },
        {
            "id": "anchor_identity_remediation_complete",
            "actual": anchor_identity_ready,
            "target": True,
            "met": anchor_identity_ready,
        },
        {
            "id": "provisional_boundaries_explicitly_adjudicated",
            "actual_interval_count": raw_boundary_count,
            "actual_classified_count": classified_boundary_count,
            "target": raw_boundary_count,
            "met": boundary_adjudication_complete,
        },
        {
            "id": "post_anchor_boundaries_production_ready",
            "actual": boundaries_production_ready,
            "target": True,
            "met": boundaries_production_ready,
        },
        {
            "id": "deterministic_replay",
            "actual": replay,
            "target": True,
            "met": replay,
        },
        {
            "id": "materialization_committed_after_validation",
            "actual_applied": materialization_applied,
            "actual_commit_eligible": commit_eligible,
            "target": True,
            "met": materialization_applied and commit_eligible,
        },
        {
            "id": "materialized_anchor_alignment",
            "actual_anchor_id": validation.get("anchor_id"),
            "actual_as_of": validation.get("as_of"),
            "actual_universe_code": validation.get("universe_code"),
            "actual_constituent_count": validation.get("expected_constituent_count"),
            "target_anchor_id": identity_anchor_id,
            "target_as_of": identity_anchor_date.isoformat(),
            "target_universe_code": identity_safe_anchor.get("universe_code", "sp500"),
            "target_constituent_count": identity_anchor_count,
            "met": materialization_anchor_aligned,
        },
        {
            "id": "materialized_provisional_snapshot_matches_anchor",
            "actual": provisional_anchor_match,
            "target": True,
            "met": provisional_anchor_match,
        },
        {
            "id": "materialized_strict_snapshot_matches_anchor",
            "actual": strict_anchor_match,
            "target": True,
            "met": strict_anchor_match,
        },
        {
            "id": "materialized_interval_integrity",
            **interval_counts,
            "target": 0,
            "met": interval_integrity,
        },
        {
            "id": "materialized_snapshot_replay",
            "actual": materialized_replay,
            "target": True,
            "met": materialized_replay,
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
    parser.add_argument("--anchor-reconciliation", required=True, type=Path)
    parser.add_argument("--boundary-audit", required=True, type=Path)
    parser.add_argument("--materialization", required=True, type=Path)
    parser.add_argument("--component-cik-audit", type=Path)
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
        anchor_reconciliation=_read(args.anchor_reconciliation),
        boundary_audit=_read(args.boundary_audit),
        materialization=_read(args.materialization),
        component_cik_audit=(
            _read(args.component_cik_audit) if args.component_cik_audit else None
        ),
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
