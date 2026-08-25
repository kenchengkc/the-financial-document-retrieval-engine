from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from fdre.evals import (
    load_cross_sectional_benchmark,
    load_jsonl_dataset,
    validate_benchmark,
    validate_cross_sectional_evidence_grounding,
)
from fdre.research.screen import ResearchScreenPlan

REPO_ROOT = Path(__file__).resolve().parents[3]
CROSS_SECTIONAL_BENCHMARK = REPO_ROOT / "data/evals/cross_sectional_benchmark.v1.jsonl"
GROUNDED_DEVELOPMENT_BENCHMARK = (
    REPO_ROOT / "data/evals/cross_sectional_benchmark.v2.dev.jsonl"
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


def test_direct_cross_sectional_evidence_does_not_rehydrate_from_source() -> None:
    direct = load_jsonl_dataset(GROUNDED_DEVELOPMENT_BENCHMARK)
    loaded_without_source = load_cross_sectional_benchmark(
        GROUNDED_DEVELOPMENT_BENCHMARK,
    )
    loaded_with_source = load_cross_sectional_benchmark(
        GROUNDED_DEVELOPMENT_BENCHMARK,
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
