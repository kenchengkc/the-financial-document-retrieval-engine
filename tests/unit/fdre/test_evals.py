from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdre.evals.datasets import (
    EvalQuestion,
    EvidenceReference,
    compute_dataset_sha256,
    evidence_fingerprint,
    load_jsonl_dataset,
    normalize_evidence_text,
    validate_benchmark,
    validate_reviewed_benchmark,
    write_jsonl_dataset,
)
from fdre.evals.metrics import (
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from fdre.evals.runner import (
    EvaluationOutcome,
    evaluate_variants,
    evaluate_variants_at_ks,
    write_eval_report,
)
from fdre.retrieval.query import RetrievalCandidate


def test_retrieval_metrics() -> None:
    ranked = [3, 1, 2, 4]
    relevant = {1, 2}
    assert recall_at_k(ranked, relevant, 3) == 1.0
    assert precision_at_k(ranked, relevant, 2) == 0.5
    assert reciprocal_rank(ranked, relevant) == 0.5
    assert ndcg_at_k(ranked, relevant, 3) == pytest.approx(0.6934, rel=1e-3)


def test_dataset_and_eval_reports_round_trip(tmp_path: Path) -> None:
    dataset_path = tmp_path / "eval.jsonl"
    questions = [
        EvalQuestion(
            question="Find revenue table",
            expected_tickers=["NVDA"],
            expected_sections=["Financial Statements"],
            relevant_evidence=[
                EvidenceReference.from_quote(
                    accession_number="0001045810-26-000001",
                    section="Financial Statements",
                    quote="Revenue table",
                    ticker="NVDA",
                )
            ],
            answer_type="table",
        )
    ]
    write_jsonl_dataset(dataset_path, questions)
    loaded = load_jsonl_dataset(dataset_path)

    def retrieve(_question: EvalQuestion) -> list[RetrievalCandidate]:
        return [
            RetrievalCandidate(
                chunk_id=2,
                text="Revenue table",
                metadata={
                    "ticker": "NVDA",
                    "section": "Financial Statements",
                    "accession_number": "0001045810-26-000001",
                },
                hybrid_score=1.0,
                rank=1,
            )
        ]

    metrics = evaluate_variants(loaded, {"Hybrid": retrieve}, k=5)
    json_path, markdown_path = write_eval_report(tmp_path, metrics, k=5)

    assert metrics[0].recall_at_k == 1.0
    assert metrics[0].table_recall_at_k == 1.0
    assert json.loads(json_path.read_text())["metrics"][0]["variant"] == "Hybrid"
    assert "| Hybrid | 1.000" in markdown_path.read_text()


def test_stable_evidence_reference_normalizes_and_validates() -> None:
    reference = EvidenceReference.from_quote(
        accession_number="0000320193-25-000079",
        section="Risk Factors",
        quote="  Supply\nconstraints MAY affect operations. ",
        ticker="AAPL",
    )

    assert reference.normalized_quote == "supply constraints may affect operations."
    assert reference.content_fingerprint == evidence_fingerprint(
        "Supply constraints may affect operations."
    )
    assert normalize_evidence_text("  A\n B  ") == "a b"


def test_eval_records_latency_abstention_entity_and_cost() -> None:
    question = EvalQuestion(
        question="What did Apple disclose?",
        expected_tickers=["AAPL"],
        relevant_chunk_ids=[2],
    )

    metrics = evaluate_variants(
        [question],
        {
            "Hybrid": lambda _question: EvaluationOutcome(
                candidates=[
                    RetrievalCandidate(
                        chunk_id=2,
                        text="Apple disclosed supply risk.",
                        metadata={"ticker": "AAPL"},
                    )
                ],
                latency_ms=12.5,
                provider_cost_usd=0.00001,
                inferred_tickers=("AAPL",),
            )
        },
        k=10,
    )[0]

    assert metrics.recall_at_k == 1.0
    assert metrics.entity_resolution_accuracy == 1.0
    assert metrics.latency_p95_ms == 12.5
    assert metrics.average_provider_cost_usd == 0.00001


def test_reviewed_benchmark_contract_rejects_incomplete_dataset() -> None:
    with pytest.raises(ValueError, match="expected 120 questions"):
        validate_reviewed_benchmark(
            [
                EvalQuestion(
                    question="Incomplete benchmark",
                    should_abstain=True,
                    metadata={"reviewed_by": "reviewer"},
                )
            ]
        )


# ---------------------------------------------------------------------------
# Part 1 — task_type, as_of, validate_benchmark, compute_dataset_sha256
# ---------------------------------------------------------------------------


def test_resolved_task_type_falls_back_to_category() -> None:
    question = EvalQuestion(
        question="What were Apple's risks?",
        category="narrative",
    )
    assert question.task_type is None
    assert question.resolved_task_type == "narrative"


def test_resolved_task_type_prefers_explicit_task_type() -> None:
    question = EvalQuestion(
        question="What changed in Apple's latest 10-K?",
        category="temporal",
        task_type="latest_filing",
    )
    assert question.resolved_task_type == "latest_filing"


def test_as_of_field_optional_and_round_trips() -> None:
    without = EvalQuestion(question="No temporal constraint")
    assert without.as_of is None

    with_date = EvalQuestion(
        question="Apple risks as of June 2024",
        as_of="2024-06-30",
    )
    assert with_date.as_of == "2024-06-30"

    with_datetime = EvalQuestion(
        question="Apple risks as of midday",
        as_of="2024-06-30T16:30:00Z",
    )
    assert with_datetime.as_of == "2024-06-30T16:30:00Z"


def test_new_fields_round_trip_through_jsonl(tmp_path: Path) -> None:
    questions = [
        EvalQuestion(
            question="Latest 10-K risk factors",
            category="temporal",
            task_type="latest_filing",
            as_of="2024-12-31",
            relevant_chunk_ids=[1],
            metadata={"reviewed_by": "test"},
        )
    ]
    path = tmp_path / "questions.jsonl"
    write_jsonl_dataset(path, questions)
    loaded = load_jsonl_dataset(path)
    assert loaded[0].task_type == "latest_filing"
    assert loaded[0].as_of == "2024-12-31"
    assert loaded[0].resolved_task_type == "latest_filing"


def test_legacy_jsonl_without_new_fields_loads_cleanly(tmp_path: Path) -> None:
    """Records written before v2 fields were added must still parse."""
    legacy_record = json.dumps(
        {
            "question": "What were Apple's revenues?",
            "split": "development",
            "category": "narrative",
            "expected_tickers": ["AAPL"],
            "relevant_chunk_ids": [42],
            "metadata": {"reviewed_by": "legacy"},
        },
        sort_keys=True,
    )
    path = tmp_path / "legacy.jsonl"
    path.write_text(legacy_record + "\n")
    loaded = load_jsonl_dataset(path)
    assert loaded[0].task_type is None
    assert loaded[0].as_of is None
    assert loaded[0].resolved_task_type == "narrative"


def test_validate_benchmark_accepts_custom_counts() -> None:
    questions = _make_reviewed_questions(count=6, dev=4, holdout=2)
    # Should pass with matching constraints
    validate_benchmark(
        questions,
        expected_count=6,
        expected_splits={"development": 4, "holdout": 2},
    )


def test_validate_benchmark_rejects_wrong_count() -> None:
    questions = _make_reviewed_questions(count=6, dev=4, holdout=2)
    with pytest.raises(ValueError, match="expected 10 questions, found 6"):
        validate_benchmark(questions, expected_count=10)


def test_validate_benchmark_rejects_wrong_split() -> None:
    questions = _make_reviewed_questions(count=6, dev=4, holdout=2)
    with pytest.raises(ValueError, match="expected 5 development"):
        validate_benchmark(
            questions,
            expected_splits={"development": 5, "holdout": 1},
        )


def test_validate_benchmark_rejects_missing_categories() -> None:
    questions = _make_reviewed_questions(count=2, dev=1, holdout=1)
    with pytest.raises(ValueError, match="missing categories"):
        validate_benchmark(
            questions,
            required_categories={"narrative", "table", "legal"},
        )


def test_validate_reviewed_benchmark_still_strict() -> None:
    """The legacy validator must still reject anything other than 120/80/40."""
    questions = _make_reviewed_questions(count=6, dev=4, holdout=2)
    with pytest.raises(ValueError, match="expected 120 questions"):
        validate_reviewed_benchmark(questions)


def test_compute_dataset_sha256_deterministic() -> None:
    questions = [
        EvalQuestion(question="Query A", relevant_chunk_ids=[1], metadata={"reviewed_by": "x"}),
        EvalQuestion(question="Query B", relevant_chunk_ids=[2], metadata={"reviewed_by": "x"}),
    ]
    hash_1 = compute_dataset_sha256(questions)
    hash_2 = compute_dataset_sha256(questions)
    assert hash_1 == hash_2
    assert len(hash_1) == 64  # SHA-256 hex digest length


def test_compute_dataset_sha256_changes_on_different_content() -> None:
    base = [
        EvalQuestion(question="Query A", relevant_chunk_ids=[1], metadata={"reviewed_by": "x"}),
    ]
    modified = [
        EvalQuestion(question="Query B", relevant_chunk_ids=[1], metadata={"reviewed_by": "x"}),
    ]
    assert compute_dataset_sha256(base) != compute_dataset_sha256(modified)


def test_existing_benchmark_loads_and_validates() -> None:
    """The real v1 benchmark must still pass unchanged."""
    benchmark_path = Path("data/evals/retrieval_benchmark.jsonl")
    if not benchmark_path.exists():
        pytest.skip("Benchmark file not present in this environment")
    questions = load_jsonl_dataset(benchmark_path)
    validate_reviewed_benchmark(questions)
    # New fields default cleanly
    for question in questions:
        assert question.task_type is None
        assert question.as_of is None
        assert question.resolved_task_type == question.category


# ---------------------------------------------------------------------------
# Part 2 — evaluate_variants_at_ks (multi-K evaluation core)
# ---------------------------------------------------------------------------


def _make_ranked_candidates(count: int) -> list[RetrievalCandidate]:
    """Build a ranking of ``count`` candidates with chunk_ids 1..count."""
    return [
        RetrievalCandidate(
            chunk_id=i,
            text=f"chunk {i}",
            metadata={"ticker": "TEST", "section": "Risk Factors"},
        )
        for i in range(1, count + 1)
    ]


def test_multi_k_recall_from_single_retrieval() -> None:
    """Known ranking: relevant items at positions 2 and 7 (1-indexed).

    Recall@5  = 1/2 = 0.5   (only item at rank 2 is within top 5)
    Recall@10 = 2/2 = 1.0   (both items within top 10)
    """
    candidates = _make_ranked_candidates(10)
    question = EvalQuestion(
        question="Test question",
        relevant_chunk_ids=[2, 7],
    )

    results = evaluate_variants_at_ks(
        [question],
        {"test": lambda _q: candidates},
        ks=(5, 10),
    )

    assert results[5][0].recall_at_k == 0.5
    assert results[10][0].recall_at_k == 1.0
    # MRR is the same regardless of K (first relevant at rank 2)
    assert results[5][0].mrr == results[10][0].mrr == 0.5


def test_retriever_called_once_per_question() -> None:
    """Each question must be retrieved exactly once, not once per K."""
    calls = 0
    candidates = _make_ranked_candidates(20)
    questions = [
        EvalQuestion(question=f"Q{i}", relevant_chunk_ids=[1])
        for i in range(3)
    ]

    def counting_retriever(_q: EvalQuestion) -> list[RetrievalCandidate]:
        nonlocal calls
        calls += 1
        return candidates

    evaluate_variants_at_ks(
        questions,
        {"test": counting_retriever},
        ks=(5, 10, 20),
    )

    assert calls == len(questions)  # not len(questions) * 3


def test_evaluate_variants_delegates_to_at_ks() -> None:
    """evaluate_variants(..., k=N) must produce identical results to
    evaluate_variants_at_ks(..., ks=(N,))[N]."""
    candidates = _make_ranked_candidates(10)
    questions = [
        EvalQuestion(question="Test", relevant_chunk_ids=[3]),
    ]

    def retrieve(_q: EvalQuestion) -> list[RetrievalCandidate]:
        return candidates

    old = evaluate_variants(questions, {"test": retrieve}, k=5)
    new = evaluate_variants_at_ks(questions, {"test": retrieve}, ks=(5,))[5]

    assert old == new


def test_evaluate_variants_at_ks_rejects_empty_ks() -> None:
    with pytest.raises(ValueError, match="ks must not be empty"):
        evaluate_variants_at_ks([], {}, ks=())


def test_evaluate_variants_at_ks_rejects_non_positive_ks() -> None:
    with pytest.raises(ValueError, match="ks must contain positive integers"):
        evaluate_variants_at_ks([], {}, ks=(0, 5))
    with pytest.raises(ValueError, match="ks must contain positive integers"):
        evaluate_variants_at_ks([], {}, ks=(-1, 10))


def test_evaluate_variants_at_ks_deduplicates_ks() -> None:
    """ks=(10, 5, 10) should behave as (5, 10)."""
    candidates = _make_ranked_candidates(10)
    questions = [
        EvalQuestion(question="Test", relevant_chunk_ids=[1]),
    ]

    results = evaluate_variants_at_ks(
        questions,
        {"test": lambda _q: candidates},
        ks=(10, 5, 10),
    )

    assert sorted(results.keys()) == [5, 10]


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_reviewed_questions(
    *,
    count: int,
    dev: int,
    holdout: int,
) -> list[EvalQuestion]:
    """Build a minimal set of reviewed questions for validator tests."""
    questions: list[EvalQuestion] = []
    for i in range(dev):
        questions.append(
            EvalQuestion(
                question=f"Dev question {i}",
                split="development",
                category="narrative",
                relevant_chunk_ids=[i],
                metadata={"reviewed_by": "test"},
            )
        )
    for i in range(holdout):
        questions.append(
            EvalQuestion(
                question=f"Holdout question {i}",
                split="holdout",
                category="narrative",
                relevant_chunk_ids=[100 + i],
                metadata={"reviewed_by": "test"},
            )
        )
    return questions
