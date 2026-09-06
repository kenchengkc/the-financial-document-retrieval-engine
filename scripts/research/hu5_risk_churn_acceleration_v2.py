"""Run the versioned HU-5 multi-class outcome amendment.

The original ``hu5_risk_churn_acceleration`` module remains the unchanged
post-closure rerun contract. This runner changes only the issuer-to-outcome
mapping according to the policy frozen before this implementation.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from fdre.research.experiment_registry import (
    build_research_experiment_manifest,
    persist_research_experiment_manifest,
    verify_research_experiment,
    write_research_experiment_manifest,
)
from fdre.research.hu5_multiclass import (
    HU5_MULTICLASS_OUTCOME_POLICY_VERSION,
    HU5MultiClassOutcomeUnavailable,
    market_symbols_for_events,
    resolve_hu5_events_multiclass,
    run_hu5_multiclass_walk_forward_signal_study,
    write_hu5_multiclass_lineage,
)
from fdre.research.hu5_universe import (
    HU5UniverseGate,
    build_hu5_universe_gate,
    load_hu5_universe_records,
    select_historical_issuer_ciks,
    write_hu5_universe_gate,
)
from fdre.research.market_data import fetch_market_bars
from fdre.research.oos_diagnostics import (
    OOSDiagnosticsConfig,
    build_oos_diagnostics,
    persist_oos_diagnostics,
    write_oos_diagnostics_report,
)
from fdre.research.oos_implementation import (
    OOSImplementationConfig,
    evaluate_oos_implementation,
    persist_oos_implementation,
    write_oos_implementation_report,
)
from fdre.research.oos_promotion import (
    OOSPromotionConfig,
    evaluate_oos_promotion,
    persist_oos_promotion,
    write_oos_promotion_report,
)
from fdre.research.oos_selection import (
    OOSSelectionConfig,
    evaluate_oos_selection_suite,
    persist_oos_selection_suite,
    write_oos_selection_report,
)
from fdre.research.panel import ResearchPanelQuery, build_research_panel
from fdre.research.risk_churn_acceleration import build_risk_churn_acceleration_events
from fdre.research.walk_forward import (
    persist_walk_forward_study,
    write_walk_forward_report,
)
from scripts.research import hu5_risk_churn_acceleration as v1

AMENDED_INSUFFICIENCY_SCHEMA_VERSION = "fdre-hu5-insufficiency-v2"


def _methodology_payload(
    event_config: object,
    walk_config: object,
) -> dict[str, object]:
    # The validated config objects are created by the unchanged runner helpers.
    payload = v1._methodology_payload(event_config, walk_config)  # type: ignore[arg-type]
    payload["issuer_outcome_policy"] = {
        "version": HU5_MULTICLASS_OUTCOME_POLICY_VERSION,
        "observation_unit": "issuer_filing_accession",
        "component_selection": "all_strict_active_securities_for_filing_cik_on_event_date",
        "component_set": "frozen_at_event_date",
        "multi_class_aggregation": "equal_weight_arithmetic_mean_total_return",
        "benchmark_adjustment": "subtract_once_after_aggregation",
        "missing_component": "fail_closed_no_renormalization",
    }
    return payload


def _write_insufficiency(
    output_dir: Path,
    *,
    reason_code: str,
    reason: str,
    gate: HU5UniverseGate,
    event_config: object,
    walk_config: object,
    details: dict[str, object] | None = None,
) -> int:
    payload = {
        "schema_version": AMENDED_INSUFFICIENCY_SCHEMA_VERSION,
        "status": "INSUFFICIENT",
        "reason_code": reason_code,
        "reason": reason,
        "code_sha": v1._git_sha(),
        "universe": {
            "universe_code": gate.universe_code,
            "window_start": gate.window_start,
            "window_end": gate.window_end,
            "day_count": gate.day_count,
            "strict_eligible_day_count": gate.strict_eligible_day_count,
            "invalid_day_count": gate.invalid_day_count,
            "gate_manifest_id": gate.gate_manifest_id,
            "input_provenance_id": gate.input_provenance_id,
        },
        "methodology": _methodology_payload(event_config, walk_config),
        "details": details or {},
    }
    manifest_id = v1._stable_digest(payload)
    artifact = {"manifest_id": manifest_id, **payload}
    (output_dir / "insufficiency-manifest.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    )
    summary = {
        "experiment_id": manifest_id,
        "primary_status": "insufficient",
        "primary_status_reason": reason,
        "primary_observation_count": 0,
        "oos_event_count": 0,
        "eligible_fold_count": 0,
        "scored_event_count": 0,
        "sector_slice_count": 0,
        "gate_manifest_id": gate.gate_manifest_id,
        "strict_eligible_day_count": gate.strict_eligible_day_count,
        "invalid_day_count": gate.invalid_day_count,
        "reason_code": reason_code,
        "issuer_outcome_policy_version": HU5_MULTICLASS_OUTCOME_POLICY_VERSION,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    note = [
        "# FDRE flagship: Risk Factors churn acceleration",
        "",
        "## HU-5 versioned amended result",
        "",
        "- Primary decision: **INSUFFICIENT**",
        f"- Reason: {reason}",
        f"- Issuer outcome policy: `{HU5_MULTICLASS_OUTCOME_POLICY_VERSION}`",
        f"- Universe gate manifest: `{gate.gate_manifest_id}`",
        f"- Strict-eligible days: {gate.strict_eligible_day_count} / {gate.day_count}",
        "- The multi-class policy was frozen before this amended runner was evaluated.",
        "- Missing component outcomes are never renormalized or guessed.",
        "",
    ]
    (output_dir / "research-note.md").write_text("\n".join(note))
    print("PRIMARY_RESULT=INSUFFICIENT")
    print("FLAGSHIP_RESULT_JSON=" + json.dumps(summary, sort_keys=True))
    return 0


def main() -> int:
    args = v1._parser().parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    event_config = v1._event_config(args.benchmark)
    walk_config = v1._walk_config()

    with Session(create_db_engine()) as session:
        records = load_hu5_universe_records(
            session,
            universe_code=v1.UNIVERSE_CODE,
            window_start=v1.RESEARCH_WINDOW_START,
            window_end=v1.RESEARCH_WINDOW_END,
        )
        gate = build_hu5_universe_gate(
            records,
            universe_code=v1.UNIVERSE_CODE,
            window_start=v1.RESEARCH_WINDOW_START,
            window_end=v1.RESEARCH_WINDOW_END,
        )
        write_hu5_universe_gate(output_dir / "universe-gate.json", gate)
        if gate.strict_eligible_day_count == 0:
            return _write_insufficiency(
                output_dir,
                reason_code="no_strict_eligible_dates",
                reason=(
                    "No date in the fixed 2010-01-01 through 2026-09-01 research "
                    "window resolves to a complete strict historical-universe snapshot."
                ),
                gate=gate,
                event_config=event_config,
                walk_config=walk_config,
            )

        ciks, sector_by_cik = select_historical_issuer_ciks(
            session,
            universe_code=v1.UNIVERSE_CODE,
            window_start=v1.RESEARCH_WINDOW_START,
            window_end=v1.RESEARCH_WINDOW_END,
            max_issuers=args.max_tickers,
            min_documents=args.min_documents,
        )
        if not ciks:
            return _write_insufficiency(
                output_dir,
                reason_code="no_historical_issuers",
                reason=(
                    "No historical-universe issuer CIK satisfies the frozen "
                    "document-depth gate."
                ),
                gate=gate,
                event_config=event_config,
                walk_config=walk_config,
            )
        panel = build_research_panel(
            session,
            ResearchPanelQuery(
                ciks=ciks,
                period_end_from=v1.RESEARCH_WINDOW_START,
                period_end_to=v1.RESEARCH_WINDOW_END,
                form_types=["10-K", "10-Q"],
                features=["risk_changes"],
                limit=10_000,
            ),
        )
        cik_by_accession = {row.accession_number: row.cik for row in panel.rows}
        sector_by_accession = {
            row.accession_number: sector_by_cik.get(row.cik, "Unknown")
            for row in panel.rows
        }
        raw_events = build_risk_churn_acceleration_events(panel.rows)
        resolved = resolve_hu5_events_multiclass(
            raw_events,
            cik_by_accession=cik_by_accession,
            records=records,
            gate=gate,
        )

    write_hu5_multiclass_lineage(output_dir / "universe-event-lineage.json", resolved)
    if resolved.unresolved_accessions:
        return _write_insufficiency(
            output_dir,
            reason_code="unresolved_issuer_outcome_mapping",
            reason=(
                "At least one otherwise eligible issuer-level filing lacks a unique, "
                "fully evidenced event-date security mapping under the frozen v1 policy."
            ),
            gate=gate,
            event_config=event_config,
            walk_config=walk_config,
            details={
                "unresolved_accession_count": len(resolved.unresolved_accessions),
                "unresolved_accessions": list(resolved.unresolved_accessions),
                "outcome_mapping_id": resolved.outcome_mapping_id,
            },
        )

    events = v1._neutralize_events(list(resolved.events), sector_by_accession)
    if len(events) < 50:
        return _write_insufficiency(
            output_dir,
            reason_code="insufficient_scored_events",
            reason=(
                f"Only {len(events)} scored events remain after strict date membership, "
                "historical identity resolution, and the unchanged neutralization rule."
            ),
            gate=gate,
            event_config=event_config,
            walk_config=walk_config,
            details={
                "resolved_event_count": len(resolved.events),
                "excluded_invalid_date": resolved.excluded_invalid_date,
                "excluded_not_member": resolved.excluded_not_member,
                "outcome_mapping_id": resolved.outcome_mapping_id,
            },
        )

    market_start = min(event.available_at.date() for event in events) - v1.timedelta(days=10)
    market_end = max(event.available_at.date() for event in events) + v1.timedelta(
        days=v1.FORWARD_BUFFER_DAYS
    )
    market_tickers = market_symbols_for_events(events, resolved.outcome_mappings)
    bars, missing = fetch_market_bars(
        market_tickers,
        market_start,
        market_end,
        benchmark=args.benchmark,
        cache_dir=Path(args.market_cache_dir) if args.market_cache_dir else None,
        cache_only=args.cache_only,
        max_uncached_fetches=args.max_uncached_market_fetches,
    )
    if missing:
        return _write_insufficiency(
            output_dir,
            reason_code="historical_market_data_incomplete",
            reason=(
                "Historical-symbol market outcomes are incomplete for the unchanged "
                "1:21/1:63/1:126 horizons."
            ),
            gate=gate,
            event_config=event_config,
            walk_config=walk_config,
            details={
                "missing_symbols": sorted(missing),
                "outcome_mapping_id": resolved.outcome_mapping_id,
            },
        )

    scored_accessions = {event.accession_number for event in events}
    scored_multiclass_count = sum(
        item.is_multiclass and item.accession_number in scored_accessions
        for item in resolved.outcome_mappings
    )
    historical_snapshot_ids = sorted({item.snapshot_id for item in resolved.lineage})
    definition = {
        **v1._base_definition(walk_config),
        "historical_universe": {
            "universe_code": gate.universe_code,
            "research_window_start": gate.window_start,
            "research_window_end": gate.window_end,
            "strict_universe_gate_manifest_id": gate.gate_manifest_id,
            "universe_input_provenance_id": gate.input_provenance_id,
            "event_universe_lineage_id": resolved.universe_lineage_id,
            "snapshot_ids": historical_snapshot_ids,
            "strict_eligible_day_count": gate.strict_eligible_day_count,
            "invalid_day_count": gate.invalid_day_count,
            "event_lineage_count": len(resolved.lineage),
        },
        "issuer_outcome_policy": {
            "version": HU5_MULTICLASS_OUTCOME_POLICY_VERSION,
            "outcome_mapping_id": resolved.outcome_mapping_id,
            "observation_unit": "issuer_filing_accession",
            "component_selection": "all_strict_active_securities_for_filing_cik_on_event_date",
            "component_set": "frozen_at_event_date",
            "multi_class_aggregation": "equal_weight_arithmetic_mean_total_return",
            "benchmark_adjustment": "subtract_once_after_aggregation",
            "missing_component": "fail_closed_no_renormalization",
            "scored_multiclass_event_count": scored_multiclass_count,
        },
    }
    dataset_version = (
        f"panel:{panel.corpus_snapshot_id}:hu5-universe:{resolved.universe_lineage_id}:"
        f"outcomes:{resolved.outcome_mapping_id}"
    )
    try:
        source = run_hu5_multiclass_walk_forward_signal_study(
            events,
            bars,
            event_config,
            walk_config,
            resolved.outcome_mappings,
            signal_name=v1.SIGNAL_NAME,
            dataset_version=dataset_version,
            feature_version=v1.FLAGSHIP_FEATURE_VERSION,
            code_sha=v1._git_sha(),
            definition=definition,
        )
    except HU5MultiClassOutcomeUnavailable as exc:
        return _write_insufficiency(
            output_dir,
            reason_code="multiclass_component_outcome_unavailable",
            reason=(
                "At least one selected multi-class security lacks a required event-window "
                "endpoint; the frozen policy forbids dropping or renormalizing that class."
            ),
            gate=gate,
            event_config=event_config,
            walk_config=walk_config,
            details={
                "outcome_mapping_id": resolved.outcome_mapping_id,
                "issue_count": len(exc.issues),
                "issues": [asdict(item) for item in exc.issues],
            },
        )

    write_walk_forward_report(output_dir / "walk-forward.json", source)
    if source.eligible_fold_count < v1.MIN_USABLE_OOS_FOLDS:
        return _write_insufficiency(
            output_dir,
            reason_code="insufficient_sealed_oos_folds",
            reason=(
                f"Only {source.eligible_fold_count} sealed OOS folds satisfy the frozen "
                f"breadth gates; HU-5 requires at least {v1.MIN_USABLE_OOS_FOLDS}."
            ),
            gate=gate,
            event_config=event_config,
            walk_config=walk_config,
            details={
                "eligible_fold_count": source.eligible_fold_count,
                "fold_count": source.fold_count,
                "source_experiment_key": source.experiment_key,
                "universe_lineage_id": resolved.universe_lineage_id,
                "outcome_mapping_id": resolved.outcome_mapping_id,
            },
        )

    diagnostics = build_oos_diagnostics(source, OOSDiagnosticsConfig())
    selection = evaluate_oos_selection_suite([diagnostics], OOSSelectionConfig())
    implementation = evaluate_oos_implementation(
        source,
        selection,
        OOSImplementationConfig(),
    )
    slices = v1._sector_slices(events, sector_by_accession)
    promotion = evaluate_oos_promotion(
        source,
        diagnostics,
        selection,
        implementation,
        slices=slices,
        config=OOSPromotionConfig(),
    )

    with Session(create_db_engine()) as session:
        persist_walk_forward_study(session, source)
        persist_oos_diagnostics(session, diagnostics)
        persist_oos_selection_suite(session, selection)
        persist_oos_implementation(session, implementation)
        persist_oos_promotion(session, promotion)
        manifest = build_research_experiment_manifest(
            source,
            diagnostics,
            selection,
            implementation,
            promotion,
        )
        persist_research_experiment_manifest(session, manifest)
        verify_research_experiment(session, manifest.experiment_id)

    write_oos_diagnostics_report(output_dir / "oos-diagnostics.json", diagnostics)
    write_oos_selection_report(output_dir / "statistical-selection.json", selection)
    write_oos_implementation_report(output_dir / "implementation.json", implementation)
    write_oos_promotion_report(output_dir / "promotion.json", promotion)
    write_research_experiment_manifest(output_dir / "manifest.json", manifest)

    primary = next(
        (item for item in promotion.decisions if item.window == v1.PRIMARY_WINDOW),
        None,
    )
    primary_observation_count = sum(
        item.window == v1.PRIMARY_WINDOW for item in source.oos_observations
    )
    primary_status = primary.status if primary is not None else "insufficient"
    primary_status_reason = (
        "Primary horizon reached the final sealed-OOS promotion layer."
        if primary is not None
        else "No final promotion decision was emitted for the primary horizon."
    )
    summary: dict[str, object] = {
        "experiment_id": manifest.experiment_id,
        "source_experiment_key": source.experiment_key,
        "signal_name": v1.SIGNAL_NAME,
        "primary_window": v1.PRIMARY_WINDOW,
        "primary_status": primary_status,
        "primary_status_reason": primary_status_reason,
        "primary_observation_count": primary_observation_count,
        "selected_issuer_count": len(ciks),
        "selected_ticker_count": len(market_tickers),
        "scored_event_count": len(events),
        "scored_multiclass_event_count": scored_multiclass_count,
        "oos_event_count": source.oos_event_count,
        "oos_observation_count": source.oos_observation_count,
        "eligible_fold_count": source.eligible_fold_count,
        "sector_slice_count": len(slices),
        "sector_slices": {name: sorted(members) for name, members in slices.items()},
        "gate_manifest_id": gate.gate_manifest_id,
        "universe_input_provenance_id": gate.input_provenance_id,
        "universe_lineage_id": resolved.universe_lineage_id,
        "outcome_mapping_id": resolved.outcome_mapping_id,
        "issuer_outcome_policy_version": HU5_MULTICLASS_OUTCOME_POLICY_VERSION,
        "historical_snapshot_count": len(historical_snapshot_ids),
        "diagnostics": [item.model_dump(mode="json") for item in diagnostics.windows],
        "selection_decisions": [
            item.model_dump(mode="json") for item in selection.decisions
        ],
        "implementation_windows": [
            item.model_dump(mode="json") for item in implementation.windows
        ],
        "promotion_decisions": [
            item.model_dump(mode="json") for item in promotion.decisions
        ],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    v1._write_note(output_dir / "research-note.md", summary)
    print("PRIMARY_RESULT=" + primary_status.upper())
    print("FLAGSHIP_RESULT_JSON=" + json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
