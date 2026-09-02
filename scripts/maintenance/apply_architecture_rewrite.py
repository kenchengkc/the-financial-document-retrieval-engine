"""One-shot path-reference migration for the repository architecture refactor."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {".ini", ".json", ".md", ".py", ".toml", ".yaml", ".yml"}
SCAN_ROOTS = (".github", "apps", "docs", "scripts", "src", "tests")
ROOT_FILES = ("AGENTS.md", "README.md", "pyproject.toml", "railway.toml")
SELF = Path(__file__).resolve()

BENCHMARKS = (
    "benchmark_ann_recall",
    "benchmark_answer",
    "benchmark_latency",
    "benchmark_retrieval",
    "build_cross_sectional_evidence_review",
    "build_reviewed_benchmark",
    "diagnose_condition_replay",
    "eval_guard",
    "evaluate_cross_sectional",
    "refine_benchmark_questions",
    "reground_benchmark_evidence",
)
INGESTION = (
    "build_listed_company_seeds",
    "build_sp500_tickers",
    "download_filings",
    "ingest_company_facts_batch",
    "ingest_sec_sample",
    "ingest_ticker_batch",
    "ingestion_lock",
    "mark_stale_ingestion_runs",
    "remediate_unchunked",
)
RESEARCH = (
    "flagship_risk_churn_acceleration",
    "hu5_risk_churn_acceleration",
    "market_cache_manifest",
    "research_archive",
    "research_experiment",
    "refresh_research_console_metrics",
    "verify_research_lineage",
)
HISTORICAL_UNIVERSE = (
    "bootstrap_current_security_master",
    "historical_component_cik_audit",
    "historical_security_seed_plan",
    "historical_universe_alias_audit",
    "historical_universe_anchor_audit",
    "historical_universe_anchor_reconciliation",
    "historical_universe_blocker_audit",
    "historical_universe_blocker_queue",
    "historical_universe_boundary_audit",
    "historical_universe_coverage",
    "historical_universe_evidence",
    "historical_universe_lineage_audit",
    "historical_universe_promote",
    "historical_universe_promotion_gate",
    "historical_universe_state_support",
    "historical_universe_strict_coverage",
    "universe_snapshot",
)


def _replacement_map() -> dict[str, str]:
    replacements: dict[str, str] = {}
    groups = (
        (BENCHMARKS, "benchmarks"),
        (INGESTION, "ingestion"),
        (RESEARCH, "research"),
        (HISTORICAL_UNIVERSE, "research/historical_universe"),
    )
    for names, folder in groups:
        module_folder = folder.replace("/", ".")
        for name in names:
            replacements[f"scripts/{name}.py"] = f"scripts/{folder}/{name}.py"
            replacements[f"scripts.{name}"] = f"scripts.{module_folder}.{name}"

    replacements["scripts/retrieval_pipeline.py"] = "scripts/pipelines/retrieval_pipeline.py"
    replacements["scripts.retrieval_pipeline"] = "scripts.pipelines.retrieval_pipeline"
    replacements["src/fdre/demo.py"] = "scripts/ingestion/seed_demo.py"
    replacements["fdre.demo"] = "scripts.ingestion.seed_demo"

    replacements.update(
        {
            "docs/architecture.md": "docs/architecture/system.md",
            "docs/feature_lineage.md": "docs/architecture/feature_lineage.md",
            "docs/eval_plan.md": "docs/evaluations/eval_plan.md",
            "docs/eval_results.md": "docs/evaluations/eval_results.md",
            "docs/historical_universe_v1.md": "docs/research/historical_universe.md",
            "docs/historical_universe_sources.md": "docs/research/historical_universe_sources.md",
            "docs/research_archive.md": "docs/research/archive.md",
            "tests/fdre/": "tests/unit/fdre/",
        }
    )
    return replacements


def _files() -> tuple[Path, ...]:
    files: list[Path] = []
    for root_name in SCAN_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            if path.resolve() == SELF:
                continue
            relative = path.relative_to(ROOT)
            if relative.parts[:2] == ("docs", "archive"):
                continue
            files.append(path)
    for name in ROOT_FILES:
        path = ROOT / name
        if path.exists():
            files.append(path)
    return tuple(sorted(set(files)))


def main() -> int:
    replacements = _replacement_map()
    changed: list[str] = []
    for path in _files():
        original = path.read_text(encoding="utf-8")
        updated = original
        for old, new in replacements.items():
            updated = updated.replace(old, new)
        if updated == original:
            continue
        path.write_text(updated, encoding="utf-8")
        changed.append(str(path.relative_to(ROOT)))

    print(f"Updated {len(changed)} files.")
    for path in changed:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
