from __future__ import annotations

import json
import statistics
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import create_db_engine
from apps.api.app.services.retrieval_service import search_documents
from fdre.evals import build_cross_sectional_screen_plan, load_cross_sectional_benchmark
import fdre.research.screen as screen_module
from fdre.retrieval.query import RetrievalCandidate, SearchFilters

DATASET = Path("data/evals/cross_sectional_benchmark.v2.development.jsonl")
OUTPUT = Path("data/processed/evals/screen-latency-profile-after.json")
TASK_COUNTS = {
    "structured_screen": 1,
    "change_screen": 1,
    "semantic_screen": 2,
    "semantic_structured_screen": 1,
}


def main() -> None:
    questions = load_cross_sectional_benchmark(DATASET)
    selected = []
    remaining = dict(TASK_COUNTS)
    for question in questions:
        task = question.resolved_task_type
        if remaining.get(task, 0) > 0:
            selected.append(question)
            remaining[task] -= 1
    assert all(value == 0 for value in remaining.values()), remaining

    settings = get_settings()
    original_panel = screen_module.build_research_panel
    original_evidence = screen_module._latest_filing_evidence
    active: dict[str, float] = {}

    def timed_panel(*args: Any, **kwargs: Any) -> Any:
        started = perf_counter()
        try:
            return original_panel(*args, **kwargs)
        finally:
            active["panel_ms"] = (perf_counter() - started) * 1000

    def timed_evidence(*args: Any, **kwargs: Any) -> Any:
        started = perf_counter()
        try:
            return original_evidence(*args, **kwargs)
        finally:
            active["evidence_filter_ms"] = (perf_counter() - started) * 1000

    screen_module.build_research_panel = timed_panel
    screen_module._latest_filing_evidence = timed_evidence

    records: list[dict[str, Any]] = []
    with Session(create_db_engine()) as session:
        for repeat in range(2):
            for question in selected:
                plan = build_cross_sectional_screen_plan(question)
                active = {}

                def semantic_search(
                    query: str,
                    filters: SearchFilters,
                    top_k: int,
                ) -> list[RetrievalCandidate]:
                    started = perf_counter()
                    try:
                        result = search_documents(
                            session,
                            settings,
                            query=query,
                            filters=filters,
                            top_k=top_k,
                        )
                        active["semantic_service_ms"] = float(result.latency_ms)
                        return result.candidates
                    finally:
                        active["semantic_search_ms"] = (perf_counter() - started) * 1000

                started = perf_counter()
                response = screen_module.execute_research_screen(
                    session,
                    plan,
                    semantic_search=semantic_search,
                )
                total_ms = (perf_counter() - started) * 1000
                known = sum(
                    active.get(key, 0.0)
                    for key in ("panel_ms", "semantic_search_ms", "evidence_filter_ms")
                )
                records.append(
                    {
                        "question_id": question.question_id,
                        "task_type": question.resolved_task_type,
                        "repeat": repeat + 1,
                        "total_ms": round(total_ms, 2),
                        "panel_ms": round(active.get("panel_ms", 0.0), 2),
                        "semantic_search_ms": round(active.get("semantic_search_ms", 0.0), 2),
                        "semantic_service_ms": round(active.get("semantic_service_ms", 0.0), 2),
                        "evidence_filter_ms": round(active.get("evidence_filter_ms", 0.0), 2),
                        "other_ms": round(max(0.0, total_ms - known), 2),
                        "matched_count": response.manifest.matched_count,
                    }
                )

    def summary(task: str, field: str) -> dict[str, float]:
        values = [float(record[field]) for record in records if record["task_type"] == task]
        ordered = sorted(values)
        return {
            "mean": round(statistics.fmean(values), 2),
            "p50": round(statistics.median(values), 2),
            "p95": round(ordered[round(0.95 * (len(ordered) - 1))], 2),
            "max": round(max(values), 2),
        }

    task_summary = {
        task: {
            field: summary(task, field)
            for field in (
                "total_ms",
                "panel_ms",
                "semantic_search_ms",
                "semantic_service_ms",
                "evidence_filter_ms",
                "other_ms",
            )
        }
        for task in TASK_COUNTS
    }
    report = {
        "base_sha": "4767412157a02ad9d4d68195243d28251848427e",
        "selected_question_ids": [question.question_id for question in selected],
        "task_summary": task_summary,
        "records": records,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(task_summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
