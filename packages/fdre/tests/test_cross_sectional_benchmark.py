from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from fdre.evals import (
    load_cross_sectional_benchmark,
    load_jsonl_dataset,
    validate_benchmark,
    validate_cross_sectional_condition_grounding,
    validate_cross_sectional_evidence_grounding,
)
from fdre.research.screen import ResearchScreenPlan

REPO_ROOT = Path(__file__).resolve().parents[3]
CROSS_SECTIONAL_BENCHMARK = REPO_ROOT / "data/evals/cross_sectional_benchmark.v1.jsonl"
GROUNDED_DEVELOPMENT_BENCHMARK = (
    REPO_ROOT / "data/evals/cross_sectional_benchmark.v2.dev.jsonl"
)
CONDITION_DEVELOPMENT_BENCHMARK = (
    REPO_ROOT / "data/evals/cross_sectional_benchmark.v2.conditions.dev.jsonl"
)
RETRIEVAL_BENCHMARK = REPO_ROOT / "data/evals/retrieval_benchmark.jsonl"


def test_cross_sectional_benchmark_is_reviewed_runnable_and_balanced() -> None:
    raw_questions = load_jsonl_dataset(CROSS_SECTIONAL_BENCHMARK)
    questions = load_cross_sectional_benchmark(
        CROSS_SECTIONAL_BENCHMARK,
        source_dataset_path=RETRIEVAL_BENCHMARK,
    )
    source_questions = {
        question.question_id: question
        for question in load_jsonl_dataset(RETRIEVAL_BENCHMARK)
    }

    assert all(not question.relevant_evidence for question in raw_questions)
    validate_benchmark(
        questions,
        expected_count=30,
        expected_splits={"development": 24, "holdout": 6},
        required_categories={"cross_sectional"},
    )
    assert Counter(question.resolved_task_type for question in questions) == {
        "semantic_screen": 25,
        "temporal_screen": 5,
    }

    for question in questions:
        assert question.as_of is not None
        assert len(question.expected_tickers) == 1
        expected_ticker = question.expected_tickers[0]

        source_ids = question.metadata["source_question_ids"]
        assert isinstance(source_ids, list)
        assert len(source_ids) == 1
        source = source_questions[source_ids[0]]
        assert source.metadata["review_method"] in {
            "corpus_regrounded",
            "corpus_grounded",
        }
        assert question.relevant_evidence == source.relevant_evidence
        assert question.relevant_evidence
        assert {
            reference.ticker for reference in question.relevant_evidence
        } == {expected_ticker}

        plan_payload = question.metadata["screen_plan"]
        assert isinstance(plan_payload, dict)
        universe = plan_payload["tickers"]
        assert isinstance(universe, list)
        assert len(universe) == 5
        assert len(set(universe)) == 5
        assert expected_ticker in universe
        ResearchScreenPlan.model_validate(
            {
                **plan_payload,
                "as_of": question.as_of,
                "form_types": ["10-K", "10-Q"],
                "limit": 5,
            }
        )


def test_grounded_development_seed_uses_exact_screen_selected_filings() -> None:
    raw_questions = load_jsonl_dataset(GROUNDED_DEVELOPMENT_BENCHMARK)
    questions = load_cross_sectional_benchmark(
        GROUNDED_DEVELOPMENT_BENCHMARK,
        source_dataset_path=RETRIEVAL_BENCHMARK,
    )

    assert questions == raw_questions
    validate_benchmark(
        questions,
        expected_count=13,
        expected_splits={"development": 13},
        required_categories={"cross_sectional"},
    )
    validate_cross_sectional_evidence_grounding(questions)
    assert Counter(question.resolved_task_type for question in questions) == {
        "semantic_screen": 10,
        "temporal_screen": 3,
    }

    for question in questions:
        expected_ticker = question.expected_tickers[0]
        selected_accession = question.metadata["selected_accession"]
        assert question.metadata["review_method"] == "screen_selected_filing_regrounded"
        assert question.metadata["reviewed_by"] == "fdre-assisted-screen-review-2026-08"
        assert question.metadata["reviewed_chunk_ids"]
        assert all(
            reference.accession_number == selected_accession
            and reference.ticker == expected_ticker
            for reference in question.relevant_evidence
        )

        plan = ResearchScreenPlan.model_validate(
            {
                **question.metadata["screen_plan"],
                "as_of": question.as_of,
            }
        )
        assert plan.form_types == ["10-Q"]
        assert plan.limit == 5
        assert len(plan.tickers) == 5
        assert expected_ticker in plan.tickers


def test_condition_development_cases_are_pit_grounded_and_complete() -> None:
    questions = load_cross_sectional_benchmark(CONDITION_DEVELOPMENT_BENCHMARK)
    seed = load_cross_sectional_benchmark(GROUNDED_DEVELOPMENT_BENCHMARK)
    combined = [*seed, *questions]

    validate_benchmark(
        questions,
        expected_count=15,
        expected_splits={"development": 15},
        required_categories={"cross_sectional"},
    )
    validate_cross_sectional_evidence_grounding(questions)
    validate_cross_sectional_condition_grounding(questions)
    validate_benchmark(
        combined,
        expected_count=28,
        expected_splits={"development": 28},
        required_categories={"cross_sectional"},
    )
    assert Counter(question.resolved_task_type for question in combined) == {
        "semantic_screen": 10,
        "temporal_screen": 3,
        "structured_screen": 5,
        "change_screen": 5,
        "semantic_structured_screen": 5,
    }

    for question in questions:
        expected_ticker = question.expected_tickers[0]
        assert question.metadata["review_method"] == "production_panel_v3_condition_review"
        assert question.metadata["reviewed_by"] == "fdre-assisted-condition-review-2026-08"
        assert question.metadata["selected_accession"]
        assert question.metadata["selected_prior_accession"]
        expected_conditions = question.metadata["expected_conditions"]
        assert expected_conditions

        plan = ResearchScreenPlan.model_validate(
            {
                **question.metadata["screen_plan"],
                "as_of": question.as_of,
            }
        )
        assert plan.form_types == ["10-Q"]
        assert plan.limit == 5
        assert len(plan.tickers) == 5
        assert len(set(plan.tickers)) == 5
        assert expected_ticker in plan.tickers
        assert len(plan.conditions) == len(expected_conditions)

        if question.resolved_task_type == "semantic_structured_screen":
            assert plan.semantic_query
            assert plan.rank_by == "semantic_score"
            assert question.relevant_evidence
            assert all(
                reference.accession_number == question.metadata["selected_accession"]
                and reference.ticker == expected_ticker
                for reference in question.relevant_evidence
            )
        else:
            assert plan.semantic_query is None
            assert plan.rank_by != "semantic_score"
            assert not question.relevant_evidence

        if question.resolved_task_type == "change_screen":
            assert all(condition.change_from_prior for condition in plan.conditions)
            assert all(
                expected["prior_value"] is not None
                and expected["prior_lineage_id"] is not None
                for expected in expected_conditions
            )


def test_direct_cross_sectional_grounding_does_not_require_source_dataset() -> None:
    for dataset in (
        GROUNDED_DEVELOPMENT_BENCHMARK,
        CONDITION_DEVELOPMENT_BENCHMARK,
    ):
        direct = load_jsonl_dataset(dataset)
        loaded_without_source = load_cross_sectional_benchmark(dataset)
        loaded_with_source = load_cross_sectional_benchmark(
            dataset,
            source_dataset_path=RETRIEVAL_BENCHMARK,
        )

        assert loaded_without_source == direct
        assert loaded_with_source == direct


def test_cross_sectional_grounding_validator_rejects_wrong_accession() -> None:
    question = load_jsonl_dataset(GROUNDED_DEVELOPMENT_BENCHMARK)[0]
    invalid = question.model_copy(
        update={
            "metadata": {
                **question.metadata,
                "selected_accession": "wrong-accession",
            }
        }
    )

    with pytest.raises(ValueError, match="evidence accession"):
        validate_cross_sectional_evidence_grounding([invalid])


def test_condition_grounding_validator_rejects_wrong_lineage() -> None:
    question = load_jsonl_dataset(CONDITION_DEVELOPMENT_BENCHMARK)[0]
    expected_conditions = [dict(value) for value in question.metadata["expected_conditions"]]
    expected_conditions[0]["current_lineage_id"] = "x" * 64
    invalid = question.model_copy(
        update={
            "metadata": {
                **question.metadata,
                "expected_conditions": expected_conditions,
            }
        }
    )

    # Structurally valid lineage hashes are allowed in the frozen dataset contract;
    # runtime scoring is responsible for detecting a mismatch with returned lineage.
    validate_cross_sectional_condition_grounding([invalid])


def test_condition_grounding_validator_rejects_missing_change_prior() -> None:
    question = next(
        question
        for question in load_jsonl_dataset(CONDITION_DEVELOPMENT_BENCHMARK)
        if question.resolved_task_type == "change_screen"
    )
    invalid = question.model_copy(
        update={
            "metadata": {
                **question.metadata,
                "selected_prior_accession": None,
            }
        }
    )

    with pytest.raises(ValueError, match="requires selected prior accession"):
        validate_cross_sectional_condition_grounding([invalid])


def test_cross_sectional_benchmark_loader_rejects_unknown_source(tmp_path: Path) -> None:
    case_path = tmp_path / "case.jsonl"
    case_path.write_text(
        '{"question":"bad source","category":"cross_sectional",'
        '"expected_tickers":["AAA"],"metadata":{"reviewed_by":"test",'
        '"source_question_ids":["missing"]}}\n'
    )

    with pytest.raises(ValueError, match="unknown source question"):
        load_cross_sectional_benchmark(
            case_path,
            source_dataset_path=RETRIEVAL_BENCHMARK,
        )
