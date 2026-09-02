from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from fdre.evals.cross_sectional import (
    CrossSectionalOutcome,
    evaluate_cross_sectional_outcomes,
)
from fdre.evals.cross_sectional_reporting import (
    slice_cross_sectional_metrics_by_task,
    write_cross_sectional_eval_report,
)
from fdre.evals.datasets import EvalQuestion, EvidenceReference
from fdre.evals.metrics import (
    issuer_precision_at_k,
    issuer_recall_at_k,
    max_issuer_evidence_share,
)
from fdre.research.screen import (
    ResearchScreenManifest,
    ResearchScreenPlan,
    ResearchScreenResponse,
    ResearchScreenRow,
)
from fdre.retrieval.query import RetrievalCandidate

AS_OF = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
TEST_LINEAGE_DIGEST = "0" * 64


def _row(
    *,
    ticker: str,
    accession: str,
    text: str,
    score: float,
    max_source_available_at: datetime | None = None,
) -> ResearchScreenRow:
    available_at = datetime(2026, 5, 1, tzinfo=UTC)
    return ResearchScreenRow(
        ticker=ticker,
        accession_number=accession,
        prior_accession_number=f"{accession}-prior",
        form_type="10-Q",
        period_end=date(2026, 3, 31),
        available_at=available_at,
        semantic_score=score,
        rank_value=score,
        conditions=[],
        evidence=[
            RetrievalCandidate(
                chunk_id=abs(hash((ticker, accession))) % 1_000_000 + 1,
                text=text,
                metadata={"ticker": ticker},
                rerank_score=score,
            )
        ],
        source_accessions=[accession, f"{accession}-prior"],
        feature_provenance={"filing_features": [accession]},
        max_source_available_at=max_source_available_at or available_at,
    )


def _response(
    rows: list[ResearchScreenRow],
    *,
    latency_ms: int,
    semantic_search_calls: int,
    max_information_timestamp: datetime | None = None,
) -> ResearchScreenResponse:
    plan = ResearchScreenPlan(
        as_of=AS_OF,
        semantic_query="AI-related capital expenditure",
    )
    return ResearchScreenResponse(
        plan=plan,
        manifest=ResearchScreenManifest(
            plan_hash="plan",
            feature_lineage_digest=TEST_LINEAGE_DIGEST,
            corpus_snapshot_id="snapshot",
            feature_version="test",
            universe_count=3,
            structured_match_count=3,
            semantic_search_calls=semantic_search_calls,
            semantic_candidate_count=len(rows),
            matched_count=len(rows),
            max_information_timestamp=max_information_timestamp or AS_OF,
        ),
        rows=rows,
        latency_ms=latency_ms,
    )


def test_issuer_metrics_deduplicate_ranked_tickers() -> None:
    ranked = ["AAPL", "aapl", "GOOGL"]
    relevant = {"GOOGL"}

    assert issuer_recall_at_k(ranked, relevant, 2) == 1.0
    assert issuer_precision_at_k(ranked, relevant, 2) == 0.5
    assert max_issuer_evidence_share(["AAPL", "AAPL", "MSFT"]) == pytest.approx(
        2 / 3
    )


def test_cross_sectional_evaluator_scores_issuers_evidence_and_zero_results() -> None:
    question = EvalQuestion(
        question_id="screen-001",
        question="Which issuers increased AI-related capex disclosure?",
        category="cross_sectional",
        task_type="semantic_structured_screen",
        expected_tickers=["aaa", "BBB"],
        relevant_evidence=[
            EvidenceReference.from_quote(
                accession_number="aaa-2026-q1",
                ticker="AAA",
                quote="AI capex evidence",
            )
        ],
        metadata={"reviewed_by": "test"},
    )
    response = _response(
        [
            _row(
                ticker="AAA",
                accession="aaa-2026-q1",
                text="AI capex evidence",
                score=0.9,
            ),
            _row(
                ticker="CCC",
                accession="ccc-2026-q1",
                text="Unrelated evidence",
                score=0.8,
            ),
        ],
        latency_ms=200,
        semantic_search_calls=1,
    )
    zero_question = EvalQuestion(
        question_id="screen-zero",
        question="Find issuers matching a deliberately empty screen.",
        category="cross_sectional",
        task_type="hard_negative",
        expected_tickers=[],
        metadata={"reviewed_by": "test"},
    )
    zero_response = _response(
        [],
        latency_ms=100,
        semantic_search_calls=0,
    )

    metrics = evaluate_cross_sectional_outcomes(
        [
            CrossSectionalOutcome(question=question, response=response),
            CrossSectionalOutcome(question=zero_question, response=zero_response),
        ],
        ks=(2, 1, 2),
    )

    assert metrics.question_count == 2
    assert metrics.ks == (1, 2)
    assert metrics.issuer_recall_at_k == {1: 0.5, 2: 0.5}
    assert metrics.issuer_precision_at_k == {1: 1.0, 2: 0.5}
    assert metrics.evidence_recall_at_k == {1: 1.0, 2: 1.0}
    assert metrics.zero_result_accuracy == 1.0
    assert metrics.pit_leakage_rate == 0.0
    assert metrics.latency_p50_ms == pytest.approx(150.0)
    assert metrics.latency_p95_ms == pytest.approx(195.0)
    assert metrics.mean_semantic_search_calls == pytest.approx(0.5)
    assert metrics.max_semantic_search_calls == 1
    assert metrics.mean_max_issuer_evidence_share == pytest.approx(0.25)

    first = metrics.per_question[0]
    assert first.expected_tickers == ("AAA", "BBB")
    assert first.returned_tickers == ("AAA", "CCC")
    assert first.missed_tickers == ("BBB",)
    assert first.false_positive_tickers == ("CCC",)
    assert first.pit_leakage is False

    second = metrics.per_question[1]
    assert second.zero_result_correct is True


def test_cross_sectional_evaluator_detects_point_in_time_leakage() -> None:
    question = EvalQuestion(
        question_id="screen-leak",
        question="Historical screen",
        category="cross_sectional",
        expected_tickers=["AAA"],
        metadata={"reviewed_by": "test"},
    )
    leaked_at = AS_OF + timedelta(seconds=1)
    response = _response(
        [
            _row(
                ticker="AAA",
                accession="aaa-2026-q1",
                text="Evidence",
                score=0.9,
                max_source_available_at=leaked_at,
            )
        ],
        latency_ms=50,
        semantic_search_calls=1,
        max_information_timestamp=leaked_at,
    )

    metrics = evaluate_cross_sectional_outcomes(
        [CrossSectionalOutcome(question=question, response=response)],
        ks=(10,),
    )

    assert metrics.pit_leakage_rate == 1.0
    assert metrics.per_question[0].pit_leakage is True


def test_cross_sectional_evaluator_validates_cutoffs() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        evaluate_cross_sectional_outcomes([], ks=())
    with pytest.raises(ValueError, match="positive integers"):
        evaluate_cross_sectional_outcomes([], ks=(0, 5))


def test_cross_sectional_reporting_slices_tasks_and_writes_deterministic_artifacts(
    tmp_path: Path,
) -> None:
    semantic_question = EvalQuestion(
        question_id="semantic-001",
        question="Find the issuer with AI capex disclosure.",
        category="cross_sectional",
        task_type="semantic_screen",
        expected_tickers=["AAA"],
        relevant_evidence=[
            EvidenceReference.from_quote(
                accession_number="aaa-2026-q1",
                ticker="AAA",
                quote="AI capex evidence",
            )
        ],
        metadata={"reviewed_by": "test"},
    )
    structured_question = EvalQuestion(
        question_id="structured-001",
        question="Find the issuer passing the structured condition.",
        category="cross_sectional",
        task_type="structured_screen",
        expected_tickers=["BBB"],
        metadata={"reviewed_by": "test"},
    )
    zero_question = EvalQuestion(
        question_id="negative-001",
        question="Return no issuers for the negative control.",
        category="cross_sectional",
        task_type="hard_negative",
        expected_tickers=[],
        metadata={"reviewed_by": "test"},
    )
    metrics = evaluate_cross_sectional_outcomes(
        [
            CrossSectionalOutcome(
                question=semantic_question,
                response=_response(
                    [
                        _row(
                            ticker="AAA",
                            accession="aaa-2026-q1",
                            text="AI capex evidence",
                            score=0.9,
                        )
                    ],
                    latency_ms=100,
                    semantic_search_calls=1,
                ),
            ),
            CrossSectionalOutcome(
                question=structured_question,
                response=_response(
                    [
                        _row(
                            ticker="CCC",
                            accession="ccc-2026-q1",
                            text="False positive",
                            score=0.8,
                        )
                    ],
                    latency_ms=300,
                    semantic_search_calls=0,
                ),
            ),
            CrossSectionalOutcome(
                question=zero_question,
                response=_response([], latency_ms=50, semantic_search_calls=0),
            ),
        ],
        ks=(1, 2),
    )

    slices = slice_cross_sectional_metrics_by_task(metrics)
    assert list(slices) == ["hard_negative", "semantic_screen", "structured_screen"]
    assert slices["semantic_screen"].issuer_recall_at_k == {1: 1.0, 2: 1.0}
    assert slices["structured_screen"].issuer_recall_at_k == {1: 0.0, 2: 0.0}
    assert slices["hard_negative"].zero_result_accuracy == 1.0
    assert slices["semantic_screen"].mean_semantic_search_calls == 1.0
    assert slices["structured_screen"].mean_semantic_search_calls == 0.0

    metadata = {
        "corpus_snapshot_id": "snapshot-1",
        "dataset_sha256": "abc123",
        "git_sha": "deadbeef",
    }
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_paths = write_cross_sectional_eval_report(
        first_dir,
        metrics,
        benchmark_metadata=metadata,
    )
    second_paths = write_cross_sectional_eval_report(
        second_dir,
        metrics,
        benchmark_metadata=metadata,
    )

    assert [path.name for path in first_paths] == [
        "cross_sectional_eval.json",
        "cross_sectional_eval.md",
        "cross_sectional_per_query.jsonl",
    ]
    for first, second in zip(first_paths, second_paths, strict=True):
        assert first.read_text() == second.read_text()

    payload = json.loads(first_paths[0].read_text())
    assert payload["metadata"] == metadata
    assert payload["overall"]["question_count"] == 3
    assert payload["overall"]["issuer_recall_at_k"] == {"1": 0.5, "2": 0.5}
    assert payload["by_task_type"]["semantic_screen"]["issuer_recall_at_k"] == {
        "1": 1.0,
        "2": 1.0,
    }
    assert payload["by_task_type"]["hard_negative"]["zero_result_accuracy"] == 1.0

    per_query = [json.loads(line) for line in first_paths[2].read_text().splitlines()]
    assert [record["question_id"] for record in per_query] == [
        "semantic-001",
        "structured-001",
        "negative-001",
    ]
    assert per_query[1]["missed_tickers"] == ["BBB"]
    assert per_query[1]["false_positive_tickers"] == ["CCC"]

    markdown = first_paths[1].read_text()
    assert "FDRE Cross-Sectional Evaluation" in markdown
    assert "Issuer Recall" in markdown
    assert "PIT leakage" in markdown
    assert "semantic_screen" in markdown
    assert "structured_screen" in markdown
    assert "hard_negative" in markdown


def test_cross_sectional_reporting_handles_empty_metrics(tmp_path: Path) -> None:
    metrics = evaluate_cross_sectional_outcomes([], ks=(5, 10))

    assert slice_cross_sectional_metrics_by_task(metrics) == {}
    paths = write_cross_sectional_eval_report(tmp_path, metrics)

    payload = json.loads(paths[0].read_text())
    assert payload["overall"]["question_count"] == 0
    assert payload["by_task_type"] == {}
    assert paths[2].read_text() == ""
    assert "No task slices available." in paths[1].read_text()
