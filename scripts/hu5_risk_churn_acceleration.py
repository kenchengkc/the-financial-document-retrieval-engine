from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections import defaultdict
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from fdre.research.composite_study import (
    CompositeEvent,
    SignalComponent,
    period_label,
    standardize_by_period,
)
from fdre.research.event_study import EventStudyConfig, EventWindow, FilingEvent
from fdre.research.experiment_registry import (
    build_research_experiment_manifest,
    persist_research_experiment_manifest,
    verify_research_experiment,
    write_research_experiment_manifest,
)
from fdre.research.hu5_universe import (
    HU5ResolvedEvents,
    HU5UniverseGate,
    build_hu5_universe_gate,
    load_hu5_universe_records,
    resolve_hu5_events,
    select_historical_issuer_ciks,
    write_hu5_universe_gate,
)
from fdre.research.market_data import DEFAULT_CACHE_DIR, fetch_market_bars
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
from fdre.research.risk_churn_acceleration import (
    RISK_CHURN_ACCELERATION_DEFINITION,
    RISK_CHURN_ACCELERATION_VERSION,
    build_risk_churn_acceleration_events,
)
from fdre.research.walk_forward import (
    WalkForwardConfig,
    persist_walk_forward_study,
    run_walk_forward_signal_study,
    write_walk_forward_report,
)

SIGNAL_NAME = "risk_factor_churn_acceleration"
PRIMARY_WINDOW = "1:63"
PREDECLARED_WINDOWS = ("1:21", PRIMARY_WINDOW, "1:126")
NEUTRALIZATION_VERSION = "period-sector-v1"
FLAGSHIP_FEATURE_VERSION = f"{RISK_CHURN_ACCELERATION_VERSION}+{NEUTRALIZATION_VERSION}"
MIN_SECTOR_SLICE_ISSUERS = 20
FORWARD_BUFFER_DAYS = 230
UNIVERSE_CODE = "sp500"
RESEARCH_WINDOW_START = date(2010, 1, 1)
RESEARCH_WINDOW_END = date(2026, 9, 1)
MIN_USABLE_OOS_FOLDS = 4
INSUFFICIENCY_SCHEMA_VERSION = "fdre-hu5-insufficiency-v1"
EVENT_LINEAGE_SCHEMA_VERSION = "fdre-hu5-event-lineage-export-v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the HU-5 historical-universe risk-churn acceleration rerun."
    )
    parser.add_argument("--output-dir", default="data/processed/flagship/risk-churn-acceleration")
    parser.add_argument(
        "--max-tickers",
        type=int,
        default=250,
        help="Legacy option name; caps historically eligible issuer CIKs, not current tickers.",
    )
    parser.add_argument("--min-documents", type=int, default=6)
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--market-cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--max-uncached-market-fetches", type=int, default=300)
    return parser


def _event_config(benchmark: str) -> EventStudyConfig:
    return EventStudyConfig(
        benchmark_ticker=benchmark,
        windows=[
            EventWindow(start=1, end=21),
            EventWindow(start=1, end=63),
            EventWindow(start=1, end=126),
        ],
        bootstrap_iterations=2000,
        random_seed=17,
    )


def _walk_config() -> WalkForwardConfig:
    return WalkForwardConfig(
        mode="expanding",
        train_months=24,
        validation_months=6,
        test_months=6,
        step_months=6,
        purge_unrealized_development=True,
        min_train_events=50,
        min_validation_events=20,
        min_test_events=20,
    )


def _base_definition(walk_config: WalkForwardConfig) -> dict[str, object]:
    return {
        **RISK_CHURN_ACCELERATION_DEFINITION,
        "neutralization": "same-sector same-filing-quarter z-score with period fallback",
        "neutralization_version": NEUTRALIZATION_VERSION,
        "primary_window": PRIMARY_WINDOW,
        "secondary_windows": ["1:21", "1:126"],
        "walk_forward": walk_config.model_dump(mode="json"),
        "multiple_testing_family": list(PREDECLARED_WINDOWS),
        "robustness_slice_rule": (
            f"all known sectors with at least {MIN_SECTOR_SLICE_ISSUERS} scored issuers"
        ),
    }


def _neutralize_events(
    events: list[FilingEvent],
    sector_by_accession: dict[str, str],
) -> list[FilingEvent]:
    composite_events = [
        CompositeEvent(
            ticker=event.ticker,
            accession_number=event.accession_number,
            available_at_period=period_label(event.available_at.date()),
            available_at=event.available_at,
            max_source_available_at=event.max_source_available_at,
            raw={SIGNAL_NAME: float(event.feature_value)},
        )
        for event in events
        if event.feature_value is not None
    ]
    standardized = standardize_by_period(
        composite_events,
        [SignalComponent(name=SIGNAL_NAME, sign=1)],
        sector_by_accession={
            event.accession_number: sector_by_accession.get(
                event.accession_number, "Unknown"
            )
            for event in events
        },
        min_group=4,
    )
    normalized: list[FilingEvent] = []
    for event in events:
        score = standardized.get(event.accession_number, {}).get(SIGNAL_NAME)
        if score is None:
            continue
        normalized.append(event.model_copy(update={"feature_value": score}))
    return normalized


def _sector_slices(
    events: list[FilingEvent],
    sector_by_accession: dict[str, str],
) -> dict[str, set[str]]:
    by_sector: dict[str, set[str]] = defaultdict(set)
    for event in events:
        sector = sector_by_accession.get(event.accession_number, "Unknown")
        if sector != "Unknown":
            by_sector[sector].add(event.ticker.upper())
    return {
        f"sector:{sector}": members
        for sector, members in sorted(by_sector.items())
        if len(members) >= MIN_SECTOR_SLICE_ISSUERS
    }


def _git_sha() -> str:
    github_sha = os.environ.get("GITHUB_SHA")
    if github_sha:
        return github_sha
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _stable_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _write_event_lineage(path: Path, resolved: HU5ResolvedEvents) -> None:
    payload = {
        "schema_version": EVENT_LINEAGE_SCHEMA_VERSION,
        "universe_lineage_id": resolved.universe_lineage_id,
        "event_count": len(resolved.lineage),
        "events": [asdict(item) for item in resolved.lineage],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _methodology_payload(
    event_config: EventStudyConfig,
    walk_config: WalkForwardConfig,
) -> dict[str, object]:
    return {
        "signal_name": SIGNAL_NAME,
        "feature_version": FLAGSHIP_FEATURE_VERSION,
        "primary_window": PRIMARY_WINDOW,
        "secondary_windows": ["1:21", "1:126"],
        "event_study_config": event_config.model_dump(mode="json"),
        "walk_forward_config": walk_config.model_dump(mode="json"),
        "implementation_config": OOSImplementationConfig().model_dump(mode="json"),
        "selection_config": OOSSelectionConfig().model_dump(mode="json"),
        "promotion_config": OOSPromotionConfig().model_dump(mode="json"),
        "neutralization_version": NEUTRALIZATION_VERSION,
    }


def _write_insufficiency(
    output_dir: Path,
    *,
    reason_code: str,
    reason: str,
    gate: HU5UniverseGate,
    event_config: EventStudyConfig,
    walk_config: WalkForwardConfig,
    details: dict[str, object] | None = None,
) -> int:
    payload = {
        "schema_version": INSUFFICIENCY_SCHEMA_VERSION,
        "status": "INSUFFICIENT",
        "reason_code": reason_code,
        "reason": reason,
        "code_sha": _git_sha(),
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
    manifest_id = _stable_digest(payload)
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
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    note = [
        "# FDRE flagship: Risk Factors churn acceleration",
        "",
        "## HU-5 sealed result",
        "",
        "- Primary decision: **INSUFFICIENT**",
        f"- Reason: {reason}",
        f"- Universe gate manifest: `{gate.gate_manifest_id}`",
        f"- Strict-eligible days: {gate.strict_eligible_day_count} / {gate.day_count}",
        "- Methodology was not changed after observing the input gate.",
        "- No partial-company universe was substituted for an invalid strict snapshot.",
        "",
    ]
    (output_dir / "research-note.md").write_text("\n".join(note))
    print("PRIMARY_RESULT=INSUFFICIENT")
    print("FLAGSHIP_RESULT_JSON=" + json.dumps(summary, sort_keys=True))
    return 0


def _write_note(path: Path, summary: dict[str, object]) -> None:
    diagnostics = summary["diagnostics"]
    decisions = summary["promotion_decisions"]
    lines = [
        "# FDRE flagship: Risk Factors churn acceleration",
        "",
        "## Precommitted hypothesis",
        "",
        (
            "Accelerating comparable-filing Risk Factors language churn predicts "
            "lower subsequent benchmark-adjusted equity returns."
        ),
        "",
        f"Primary horizon: **{PRIMARY_WINDOW}** sessions.",
        "Secondary horizons: **1:21** and **1:126** sessions.",
        "",
        "## Sealed OOS result",
        "",
        f"- Experiment ID: `{summary['experiment_id']}`",
        f"- Primary decision: **{str(summary['primary_status']).upper()}**",
        f"- Primary OOS observations: {summary['primary_observation_count']}",
        f"- Primary status detail: {summary['primary_status_reason']}",
        f"- OOS events: {summary['oos_event_count']}",
        f"- Eligible folds: {summary['eligible_fold_count']}",
        f"- Scored PIT filing events: {summary['scored_event_count']}",
        f"- Strict universe gate: `{summary['gate_manifest_id']}`",
        f"- Event-universe lineage: `{summary['universe_lineage_id']}`",
        f"- Predeclared robustness slices: {summary['sector_slice_count']}",
        "- Live-trading readiness: **false** (research evidence only)",
        "",
        "## OOS diagnostics",
        "",
        "| Window | IC mean | ICIR | Positive IC share | Long-short mean |",
        "|---|---:|---:|---:|---:|",
    ]
    if isinstance(diagnostics, list):
        for item in diagnostics:
            if not isinstance(item, dict):
                continue
            lines.append(
                "| {window} | {ic_mean} | {icir} | {positive_ic_share} | "
                "{long_short_mean} |".format(
                    window=item.get("window"),
                    ic_mean=item.get("ic_mean"),
                    icir=item.get("icir"),
                    positive_ic_share=item.get("positive_ic_share"),
                    long_short_mean=item.get("long_short_mean"),
                )
            )
    lines.extend(["", "## Final decisions", ""])
    if isinstance(decisions, list):
        for item in decisions:
            if isinstance(item, dict):
                lines.append(
                    f"- `{item.get('window')}`: **{str(item.get('status')).upper()}** — "
                    + ("; ".join(item.get("reasons", [])) or "all predeclared gates passed")
                )
    lines.extend(
        [
            "",
            "The decision is emitted by the predeclared statistical, implementation, "
            "and robustness gates. It is not manually upgraded after observing returns.",
            "",
        ]
    )
    path.write_text("\n".join(lines))


def main() -> int:
    args = _parser().parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    event_config = _event_config(args.benchmark)
    walk_config = _walk_config()

    with Session(create_db_engine()) as session:
        records = load_hu5_universe_records(
            session,
            universe_code=UNIVERSE_CODE,
            window_start=RESEARCH_WINDOW_START,
            window_end=RESEARCH_WINDOW_END,
        )
        gate = build_hu5_universe_gate(
            records,
            universe_code=UNIVERSE_CODE,
            window_start=RESEARCH_WINDOW_START,
            window_end=RESEARCH_WINDOW_END,
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
            universe_code=UNIVERSE_CODE,
            window_start=RESEARCH_WINDOW_START,
            window_end=RESEARCH_WINDOW_END,
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
                period_end_from=RESEARCH_WINDOW_START,
                period_end_to=RESEARCH_WINDOW_END,
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
        resolved = resolve_hu5_events(
            raw_events,
            cik_by_accession=cik_by_accession,
            records=records,
            gate=gate,
        )

    _write_event_lineage(output_dir / "universe-event-lineage.json", resolved)
    if resolved.ambiguous_accessions:
        return _write_insufficiency(
            output_dir,
            reason_code="ambiguous_security_mapping",
            reason=(
                "At least one otherwise eligible issuer-level filing maps to multiple "
                "active securities or lacks stable CIK lineage; HU-5 will not guess a share class."
            ),
            gate=gate,
            event_config=event_config,
            walk_config=walk_config,
            details={
                "ambiguous_accession_count": len(resolved.ambiguous_accessions),
                "ambiguous_accessions": list(resolved.ambiguous_accessions),
            },
        )

    events = _neutralize_events(list(resolved.events), sector_by_accession)
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
            },
        )

    market_start = min(event.available_at.date() for event in events) - timedelta(days=10)
    market_end = max(event.available_at.date() for event in events) + timedelta(
        days=FORWARD_BUFFER_DAYS
    )
    market_tickers = sorted({event.ticker.upper() for event in events})
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
            details={"missing_symbols": sorted(missing)},
        )

    historical_snapshot_ids = sorted({item.snapshot_id for item in resolved.lineage})
    definition = {
        **_base_definition(walk_config),
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
    }
    dataset_version = (
        f"panel:{panel.corpus_snapshot_id}:hu5-universe:{resolved.universe_lineage_id}"
    )
    source = run_walk_forward_signal_study(
        events,
        bars,
        event_config,
        walk_config,
        signal_name=SIGNAL_NAME,
        dataset_version=dataset_version,
        feature_version=FLAGSHIP_FEATURE_VERSION,
        code_sha=_git_sha(),
        definition=definition,
    )
    write_walk_forward_report(output_dir / "walk-forward.json", source)
    if source.eligible_fold_count < MIN_USABLE_OOS_FOLDS:
        return _write_insufficiency(
            output_dir,
            reason_code="insufficient_sealed_oos_folds",
            reason=(
                f"Only {source.eligible_fold_count} sealed OOS folds satisfy the frozen "
                f"breadth gates; HU-5 requires at least {MIN_USABLE_OOS_FOLDS}."
            ),
            gate=gate,
            event_config=event_config,
            walk_config=walk_config,
            details={
                "eligible_fold_count": source.eligible_fold_count,
                "fold_count": source.fold_count,
                "source_experiment_key": source.experiment_key,
                "universe_lineage_id": resolved.universe_lineage_id,
            },
        )

    diagnostics = build_oos_diagnostics(source, OOSDiagnosticsConfig())
    selection = evaluate_oos_selection_suite([diagnostics], OOSSelectionConfig())
    implementation = evaluate_oos_implementation(
        source,
        selection,
        OOSImplementationConfig(),
    )
    slices = _sector_slices(events, sector_by_accession)
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
        (item for item in promotion.decisions if item.window == PRIMARY_WINDOW),
        None,
    )
    primary_observation_count = sum(
        item.window == PRIMARY_WINDOW for item in source.oos_observations
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
        "signal_name": SIGNAL_NAME,
        "primary_window": PRIMARY_WINDOW,
        "primary_status": primary_status,
        "primary_status_reason": primary_status_reason,
        "primary_observation_count": primary_observation_count,
        "selected_issuer_count": len(ciks),
        "selected_ticker_count": len(market_tickers),
        "scored_event_count": len(events),
        "oos_event_count": source.oos_event_count,
        "oos_observation_count": source.oos_observation_count,
        "eligible_fold_count": source.eligible_fold_count,
        "sector_slice_count": len(slices),
        "sector_slices": {name: sorted(members) for name, members in slices.items()},
        "gate_manifest_id": gate.gate_manifest_id,
        "universe_input_provenance_id": gate.input_provenance_id,
        "universe_lineage_id": resolved.universe_lineage_id,
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
    _write_note(output_dir / "research-note.md", summary)
    print("PRIMARY_RESULT=" + primary_status.upper())
    print("FLAGSHIP_RESULT_JSON=" + json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
