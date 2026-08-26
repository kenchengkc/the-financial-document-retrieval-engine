from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import create_db_engine
from fdre.evals import (
    build_cross_sectional_screen_plan,
    load_cross_sectional_benchmark,
    validate_cross_sectional_condition_grounding,
)
from fdre.evals.datasets import EvalQuestion
from fdre.research.screen import ResearchScreenResponse, ScreenConditionResult
from scripts.eval_guard import require_neon_optin
from scripts.evaluate_cross_sectional import _production_screen_executor

DEFAULT_DATASET = "data/evals/cross_sectional_benchmark.v2.conditions.dev.jsonl"
DEFAULT_SOURCE_DATASET = "data/evals/retrieval_benchmark.jsonl"
DEFAULT_OUTPUT = "data/processed/evals/condition-replay-diagnostic.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Explain field-level mismatches in reviewed cross-sectional conditions"
    )
    parser.add_argument("dataset", nargs="?", default=DEFAULT_DATASET)
    parser.add_argument("--source-dataset", default=DEFAULT_SOURCE_DATASET)
    parser.add_argument("--split", default="development")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    require_neon_optin()
    questions = load_cross_sectional_benchmark(
        args.dataset,
        source_dataset_path=args.source_dataset,
    )
    validate_cross_sectional_condition_grounding(questions)
    questions = [question for question in questions if question.split == args.split]
    questions = [
        question for question in questions if question.metadata.get("expected_conditions")
    ]
    if not questions:
        raise ValueError(f"No reviewed-condition questions selected for split {args.split!r}")

    settings = get_settings()
    records: list[dict[str, Any]] = []
    mismatch_counts: Counter[str] = Counter()
    exact_replay_count = 0
    semantic_replay_count = 0
    with Session(create_db_engine()) as session:
        execute_screen = _production_screen_executor(session, settings)
        for question in questions:
            response = execute_screen(build_cross_sectional_screen_plan(question))
            record = diagnose_condition_replay(question, response)
            records.append(record)
            for field in record["mismatch_fields"]:
                mismatch_counts[field] += 1
            exact_replay_count += int(not record["mismatch_fields"])
            semantic_replay_count += int(record["condition_semantics_match"])

    payload = {
        "dataset": args.dataset,
        "split": args.split,
        "question_count": len(records),
        "exact_replay_count": exact_replay_count,
        "exact_replay_accuracy": exact_replay_count / len(records),
        "condition_semantics_match_count": semantic_replay_count,
        "condition_semantics_accuracy": semantic_replay_count / len(records),
        "mismatch_field_counts": dict(sorted(mismatch_counts.items())),
        "records": records,
    }
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in payload.items() if key != "records"}, indent=2))


def diagnose_condition_replay(
    question: EvalQuestion,
    response: ResearchScreenResponse,
) -> dict[str, Any]:
    expected_ticker = question.expected_tickers[0].upper()
    gold_rows = [row for row in response.rows if row.ticker.upper() == expected_ticker]
    mismatch_fields: set[str] = set()
    if len(gold_rows) != 1:
        return {
            "question_id": question.question_id or "",
            "ticker": expected_ticker,
            "condition_semantics_match": False,
            "mismatch_fields": ["gold_row"],
            "conditions": [],
        }

    row = gold_rows[0]
    expected_accession = question.metadata.get("selected_accession")
    if expected_accession != row.accession_number:
        mismatch_fields.add("selected_accession")
    expected_prior = question.metadata.get("selected_prior_accession")
    if expected_prior is not None and expected_prior != row.prior_accession_number:
        mismatch_fields.add("selected_prior_accession")

    condition_records: list[dict[str, Any]] = []
    expected_conditions = question.metadata.get("expected_conditions", [])
    for index, expected in enumerate(expected_conditions):
        actual = _matching_condition(response, expected_ticker, expected)
        if actual is None:
            mismatch_fields.add("condition_identity")
            condition_records.append(
                {
                    "index": index,
                    "metric": expected.get("metric"),
                    "mismatch_fields": ["condition_identity"],
                    "expected": expected,
                    "actual": None,
                }
            )
            continue

        condition_mismatches = _condition_mismatches(expected, actual)
        mismatch_fields.update(condition_mismatches)
        current_lineage = row.feature_lineage.get(actual.feature)
        prior_lineage = row.prior_feature_lineage.get(actual.feature)
        condition_records.append(
            {
                "index": index,
                "metric": actual.metric,
                "mismatch_fields": sorted(condition_mismatches),
                "expected": expected,
                "actual": actual.model_dump(mode="json"),
                "actual_current_lineage": (
                    current_lineage.model_dump(mode="json")
                    if current_lineage is not None
                    else None
                ),
                "actual_prior_lineage": (
                    prior_lineage.model_dump(mode="json")
                    if prior_lineage is not None
                    else None
                ),
            }
        )

    semantic_fields = {
        "selected_accession",
        "selected_prior_accession",
        "condition_identity",
        "feature",
        "passed",
        "current_value",
        "prior_value",
        "observed_value",
        "source_accessions",
    }
    return {
        "question_id": question.question_id or "",
        "ticker": expected_ticker,
        "selected_accession": {
            "expected": expected_accession,
            "actual": row.accession_number,
        },
        "selected_prior_accession": {
            "expected": expected_prior,
            "actual": row.prior_accession_number,
        },
        "condition_semantics_match": not bool(mismatch_fields & semantic_fields),
        "mismatch_fields": sorted(mismatch_fields),
        "response_corpus_snapshot_id": response.manifest.corpus_snapshot_id,
        "conditions": condition_records,
    }


def _matching_condition(
    response: ResearchScreenResponse,
    ticker: str,
    expected: dict[str, Any],
) -> ScreenConditionResult | None:
    rows = [row for row in response.rows if row.ticker.upper() == ticker]
    if len(rows) != 1:
        return None
    matches = [
        condition
        for condition in rows[0].conditions
        if condition.metric == expected.get("metric")
        and condition.operator == expected.get("operator")
        and condition.change_from_prior == bool(expected.get("change_from_prior", False))
        and _float_matches(condition.threshold, expected.get("threshold"))
    ]
    return matches[0] if len(matches) == 1 else None


def _condition_mismatches(
    expected: dict[str, Any],
    actual: ScreenConditionResult,
) -> set[str]:
    mismatches: set[str] = set()
    if actual.feature != expected.get("feature"):
        mismatches.add("feature")
    if actual.passed != bool(expected.get("passed")):
        mismatches.add("passed")
    if not _optional_float_matches(actual.current_value, expected.get("current_value")):
        mismatches.add("current_value")
    if not _optional_float_matches(actual.prior_value, expected.get("prior_value")):
        mismatches.add("prior_value")
    if not _optional_float_matches(actual.observed_value, expected.get("observed_value")):
        mismatches.add("observed_value")
    if actual.current_lineage_id != expected.get("current_lineage_id"):
        mismatches.add("current_lineage_id")
    if actual.prior_lineage_id != expected.get("prior_lineage_id"):
        mismatches.add("prior_lineage_id")
    if actual.source_accessions != expected.get("source_accessions"):
        mismatches.add("source_accessions")
    return mismatches


def _float_matches(actual: float, expected: Any) -> bool:
    if isinstance(expected, bool) or not isinstance(expected, (int, float)):
        return False
    return math.isclose(actual, float(expected), rel_tol=1e-9, abs_tol=1e-12)


def _optional_float_matches(actual: float | None, expected: Any) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None
    return _float_matches(actual, expected)


if __name__ == "__main__":
    main()
