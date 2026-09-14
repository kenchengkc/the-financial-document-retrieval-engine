from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company, Document
from fdre.research.experiments.event_study import EventStudyConfig, EventWindow, FilingEvent
from fdre.research.experiments.feature_replay import (
    build_risk_churn_feature_replay_input,
    persist_risk_churn_feature_replay_input,
    replay_risk_churn_feature_input,
    write_risk_churn_feature_replay_input,
)
from fdre.research.experiments.panel_replay import (
    build_risk_churn_panel_replay_input,
    persist_risk_churn_panel_replay_input,
    write_risk_churn_panel_replay_input,
)
from fdre.research.experiments.registry import (
    build_research_experiment_manifest,
    persist_research_experiment_manifest,
    verify_research_experiment,
    write_research_experiment_manifest,
)
from fdre.research.experiments.replay_input import (
    build_walk_forward_replay_input,
    persist_walk_forward_replay_input,
    write_walk_forward_replay_input,
)
from fdre.research.experiments.walk_forward import (
    WalkForwardConfig,
    persist_walk_forward_study,
    run_walk_forward_signal_study,
    write_walk_forward_report,
)
from fdre.research.market_data import DEFAULT_CACHE_DIR, fetch_market_bars
from fdre.research.oos.diagnostics import (
    OOSDiagnosticsConfig,
    build_oos_diagnostics,
    persist_oos_diagnostics,
    write_oos_diagnostics_report,
)
from fdre.research.oos.implementation import (
    OOSImplementationConfig,
    evaluate_oos_implementation,
    persist_oos_implementation,
    write_oos_implementation_report,
)
from fdre.research.oos.promotion import (
    OOSPromotionConfig,
    evaluate_oos_promotion,
    persist_oos_promotion,
    write_oos_promotion_report,
)
from fdre.research.oos.selection import (
    OOSSelectionConfig,
    evaluate_oos_selection_suite,
    persist_oos_selection_suite,
    write_oos_selection_report,
)
from fdre.research.panel import ResearchPanelQuery, build_research_panel
from fdre.research.signals.risk_churn_acceleration import (
    RISK_CHURN_ACCELERATION_DEFINITION,
    RISK_CHURN_ACCELERATION_VERSION,
    RISK_CHURN_NEUTRALIZATION_VERSION,
    RISK_CHURN_SIGNAL_NAME,
)

SIGNAL_NAME = RISK_CHURN_SIGNAL_NAME
PRIMARY_WINDOW = "1:63"
PREDECLARED_WINDOWS = ("1:21", PRIMARY_WINDOW, "1:126")
NEUTRALIZATION_VERSION = RISK_CHURN_NEUTRALIZATION_VERSION
FLAGSHIP_FEATURE_VERSION = f"{RISK_CHURN_ACCELERATION_VERSION}+{NEUTRALIZATION_VERSION}"
MIN_SECTOR_SLICE_ISSUERS = 20
FORWARD_BUFFER_DAYS = 230


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the precommitted FDRE risk-churn acceleration flagship study."
    )
    parser.add_argument("--output-dir", default="data/processed/flagship/risk-churn-acceleration")
    parser.add_argument("--max-tickers", type=int, default=250)
    parser.add_argument("--min-documents", type=int, default=6)
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--market-cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--max-uncached-market-fetches", type=int, default=300)
    return parser


def _select_universe(
    session: Session,
    *,
    max_tickers: int,
    min_documents: int,
) -> tuple[list[str], dict[str, str]]:
    rows = session.execute(
        select(Company.ticker, Company.sector, func.count(Document.id).label("documents"))
        .join(Document, Document.company_id == Company.id)
        .where(
            Document.form_type.in_(["10-K", "10-Q"]),
            Document.available_at.is_not(None),
        )
        .group_by(Company.id, Company.ticker, Company.sector)
        .having(func.count(Document.id) >= min_documents)
        .order_by(func.count(Document.id).desc(), Company.ticker)
        .limit(max_tickers)
    ).all()
    tickers = [str(row.ticker).upper() for row in rows]
    sectors = {str(row.ticker).upper(): str(row.sector or "Unknown") for row in rows}
    return tickers, sectors


def _sector_slices(
    events: list[FilingEvent],
    sector_by_ticker: dict[str, str],
) -> dict[str, set[str]]:
    by_sector: dict[str, set[str]] = defaultdict(set)
    for event in events:
        sector = sector_by_ticker.get(event.ticker.upper(), "Unknown")
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


def _primary_result_status(
    primary_observation_count: int,
    decision_status: str | None,
) -> tuple[str, str]:
    if decision_status is not None:
        return decision_status, "Primary horizon reached the final sealed-OOS promotion layer."
    if primary_observation_count == 0:
        return (
            "insufficient_not_yet_realized",
            "No sealed-OOS observations have a fully realized primary-horizon outcome "
            "at evaluation time.",
        )
    return (
        "insufficient_no_promotion_decision",
        "Primary-horizon observations exist but no final promotion decision was emitted.",
    )


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
            row_template = (
                "| {window} | {ic_mean} | {icir} | {positive_ic_share} | "
                "{long_short_mean} |"
            )
            lines.append(
                row_template.format(
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

    # Read the point-in-time research inputs, then close the transaction before
    # potentially slow external market-data I/O. This avoids leaving PostgreSQL
    # idle-in-transaction while providers throttle or the workflow retries.
    with Session(create_db_engine()) as session:
        tickers, sector_by_ticker = _select_universe(
            session,
            max_tickers=args.max_tickers,
            min_documents=args.min_documents,
        )
        if not tickers:
            raise RuntimeError("flagship universe is empty")
        panel = build_research_panel(
            session,
            ResearchPanelQuery(
                tickers=tickers,
                form_types=["10-K", "10-Q"],
                features=["risk_changes"],
                limit=10_000,
            ),
        )
        panel_input = build_risk_churn_panel_replay_input(session, panel)
        feature_input = build_risk_churn_feature_replay_input(
            panel.rows,
            sector_by_ticker,
        )
        dataset_version = feature_input.dataset_version
        events = replay_risk_churn_feature_input(feature_input)

    if len(events) < 50:
        raise RuntimeError(
            f"flagship sample has only {len(events)} scored PIT events; minimum is 50"
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
        raise RuntimeError(
            "flagship market-data coverage is incomplete: " + ", ".join(sorted(missing))
        )

    event_config = EventStudyConfig(
        benchmark_ticker=args.benchmark,
        windows=[
            EventWindow(start=1, end=21),
            EventWindow(start=1, end=63),
            EventWindow(start=1, end=126),
        ],
        bootstrap_iterations=2000,
        random_seed=17,
    )
    walk_config = WalkForwardConfig(
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
    definition = {
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
    code_sha = _git_sha()
    replay_input = build_walk_forward_replay_input(
        events,
        bars,
        event_config,
        walk_config,
        signal_name=SIGNAL_NAME,
        dataset_version=dataset_version,
        feature_version=FLAGSHIP_FEATURE_VERSION,
        code_sha=code_sha,
        definition=definition,
    )
    source = run_walk_forward_signal_study(
        events,
        bars,
        event_config,
        walk_config,
        signal_name=SIGNAL_NAME,
        dataset_version=dataset_version,
        feature_version=FLAGSHIP_FEATURE_VERSION,
        code_sha=code_sha,
        definition=definition,
    )
    diagnostics = build_oos_diagnostics(source, OOSDiagnosticsConfig())
    selection = evaluate_oos_selection_suite([diagnostics], OOSSelectionConfig())
    implementation = evaluate_oos_implementation(
        source,
        selection,
        OOSImplementationConfig(),
    )
    slices = _sector_slices(events, sector_by_ticker)
    promotion = evaluate_oos_promotion(
        source,
        diagnostics,
        selection,
        implementation,
        slices=slices,
        config=OOSPromotionConfig(),
    )

    # Persistence uses a fresh short-lived database transaction after all network
    # and CPU-heavy evaluation has completed.
    with Session(create_db_engine()) as session:
        persist_risk_churn_panel_replay_input(session, panel_input)
        persist_risk_churn_feature_replay_input(session, feature_input)
        persist_walk_forward_replay_input(session, replay_input)
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
            promotion_slices=slices,
            walk_forward_input=replay_input,
            feature_input=feature_input,
            panel_input=panel_input,
        )
        persist_research_experiment_manifest(session, manifest)
        verify_research_experiment(session, manifest.experiment_id)

    write_risk_churn_panel_replay_input(
        output_dir / "panel-replay-input.json",
        panel_input,
    )
    write_risk_churn_feature_replay_input(
        output_dir / "feature-replay-input.json",
        feature_input,
    )
    write_walk_forward_replay_input(output_dir / "walk-forward-replay-input.json", replay_input)
    write_walk_forward_report(output_dir / "walk-forward.json", source)
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
    primary_status, primary_status_reason = _primary_result_status(
        primary_observation_count,
        primary.status if primary is not None else None,
    )
    summary: dict[str, object] = {
        "experiment_id": manifest.experiment_id,
        "source_experiment_key": source.experiment_key,
        "panel_replay_input_key": panel_input.input_key,
        "feature_replay_input_key": feature_input.input_key,
        "walk_forward_replay_input_key": replay_input.input_key,
        "signal_name": SIGNAL_NAME,
        "primary_window": PRIMARY_WINDOW,
        "primary_status": primary_status,
        "primary_status_reason": primary_status_reason,
        "primary_observation_count": primary_observation_count,
        "selected_ticker_count": len(tickers),
        "scored_event_count": len(events),
        "oos_event_count": source.oos_event_count,
        "oos_observation_count": source.oos_observation_count,
        "eligible_fold_count": source.eligible_fold_count,
        "sector_slice_count": len(slices),
        "sector_slices": {name: sorted(members) for name, members in slices.items()},
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
