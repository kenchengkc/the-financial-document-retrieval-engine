from __future__ import annotations

from datetime import UTC, date, datetime
from typing import cast

import pytest
from scripts.evaluate_cross_sectional import (
    build_cross_sectional_benchmark_metadata,
    parse_args,
)
from sqlalchemy.orm import Session

from apps.api.app.config import Settings
from fdre.evals.cross_sectional_runner import (
    build_cross_sectional_screen_plan,
    run_cross_sectional_benchmark,
)
from fdre.evals.datasets import EvalQuestion, EvidenceReference
from fdre.research.screen import (
    ResearchScreenManifest,
    ResearchScreenPlan,
    ResearchScreenResponse,
    ResearchScreenRow,
)
from fdre.retrieval.query import RetrievalCandidate

AS_OF = "2026-07-31T23:59:59+00:00"
AVAILABLE_AT = datetime(2026, 7, 1, tzinfo=UTC)
TEST_LINEAGE_DIGEST = "0" * 64


def _question() -> EvalQuestion:
    return EvalQuestion(
        question_id="development-xs-test",
        question="Which issuer matches the reviewed disclosure?",
        split="development",
        category="cross_sectional",
        task_type="semantic_screen",
        as_of=AS_OF,
        expected_tickers=["AAA"],
        relevant_evidence=[
            EvidenceReference.from_quote(
                accession_number="aaa-2026-q2",
                section="Risk Factors",
                ticker="AAA",
                quote="reviewed cybersecurity risk excerpt",
            )
        ],
        metadata={
            "reviewed_by": "test",
            "screen_plan": {
                "tickers": ["AAA", "BBB", "CCC", "DDD", "EEE"],
                "semantic_query": "cybersecurity risk",
            },
        },
    )


def _response(plan: ResearchScreenPlan) -> ResearchScreenResponse:
    return ResearchScreenResponse(
        plan=plan,
        manifest=ResearchScreenManifest(
            plan_hash="plan",
            feature_lineage_digest=TEST_LINEAGE_DIGEST,
            corpus_snapshot_id="snapshot",
            feature_version="test",
            universe_count=5,
            structured_match_count=5,
            semantic_search_calls=1,
            semantic_candidate_count=5,
            matched_count=1,
            max_information_timestamp=AVAILABLE_AT,
        ),
        rows=[
            ResearchScreenRow(
                ticker="AAA",
                accession_number="aaa-2026-q2",
                prior_accession_number="aaa-2025-q2",
                form_type="10-Q",
                period_end=date(2026, 6, 30),
                available_at=AVAILABLE_AT,
                semantic_score=0.9,
                rank_value=0.9,
                conditions=[],
                evidence=[
                    RetrievalCandidate(
                        chunk_id=1,
                        text=(
                            "Longer chunk prefix reviewed cybersecurity risk excerpt "
                            "with additional filing context after the reviewed quote."
                        ),
                        metadata={
                            "ticker": "AAA",
                            "section": "Risk Factors",
                            "accession_number": "aaa-2026-q2",
                        },
                        rerank_score=0.9,
                    )
                ],
                source_accessions=["aaa-2026-q2", "aaa-2025-q2"],
                feature_provenance={"filing_features": ["aaa-2026-q2"]},
                max_source_available_at=AVAILABLE_AT,
            )
        ],
    )


def test_cross_sectional_runner_builds_plan_and_scores_reviewed_excerpt() -> None:
    question = _question()
    observed_plans: list[ResearchScreenPlan] = []

    def execute(plan: ResearchScreenPlan) -> ResearchScreenResponse:
        observed_plans.append(plan)
        return _response(plan)

    metrics = run_cross_sectional_benchmark(
        [question],
        execute_screen=execute,
        ks=(5, 1, 3, 1),
    )

    assert len(observed_plans) == 1
    assert observed_plans[0].tickers == ["AAA", "BBB", "CCC", "DDD", "EEE"]
    assert observed_plans[0].as_of.isoformat() == AS_OF
    assert metrics.ks == (1, 3, 5)
    assert metrics.issuer_recall_at_k == {1: 1.0, 3: 1.0, 5: 1.0}
    assert metrics.issuer_precision_at_k == {
        1: 1.0,
        3: pytest.approx(1 / 3),
        5: pytest.approx(1 / 5),
    }
    assert metrics.evidence_recall_at_k == {1: 1.0, 3: 1.0, 5: 1.0}
    assert metrics.pit_leakage_rate == 0.0
    assert metrics.max_semantic_search_calls == 1


def test_cross_sectional_screen_plan_requires_top_level_as_of_and_plan() -> None:
    missing_as_of = _question().model_copy(update={"as_of": None})
    with pytest.raises(ValueError, match="missing as_of"):
        build_cross_sectional_screen_plan(missing_as_of)

    missing_plan = _question().model_copy(update={"metadata": {"reviewed_by": "test"}})
    with pytest.raises(ValueError, match=r"missing metadata\.screen_plan"):
        build_cross_sectional_screen_plan(missing_plan)

    duplicate_as_of = _question().model_copy(
        update={
            "metadata": {
                "reviewed_by": "test",
                "screen_plan": {
                    "as_of": AS_OF,
                    "semantic_query": "cybersecurity risk",
                },
            }
        }
    )
    with pytest.raises(ValueError, match="must use the top-level as_of"):
        build_cross_sectional_screen_plan(duplicate_as_of)


def test_cross_sectional_cli_defaults_to_development_and_rank_cutoffs() -> None:
    args = parse_args([])

    assert args.split == "development"
    assert args.ks == [1, 3, 5]


class _FakeSession:
    def __init__(self) -> None:
        self.values = iter((3_195, 3_030_425, 3_030_425))

    def scalar(self, _statement: object) -> int:
        return next(self.values)


def test_cross_sectional_metadata_pins_dataset_corpus_and_provider_state() -> None:
    question = _question()
    settings = Settings(
        EMBEDDING_PROVIDER="local_hash",
        EMBEDDING_MODEL="local-hash-v1",
        EMBEDDING_DIMENSIONS=512,
        RERANKER_PROVIDER="none",
    )

    metadata = build_cross_sectional_benchmark_metadata(
        cast(Session, _FakeSession()),
        settings=settings,
        dataset="data/evals/cross_sectional_benchmark.v1.jsonl",
        dataset_sha256="dataset-sha",
        hydrated_dataset_sha256="hydrated-sha",
        source_dataset="data/evals/retrieval_benchmark.jsonl",
        source_dataset_sha256="source-sha",
        evaluated_subset_sha256="subset-sha",
        split="development",
        questions=[question],
        ks=(1, 3, 5),
    )

    assert metadata["benchmark_name"] == "FDRE Cross-Sectional v1"
    assert metadata["dataset_sha256"] == "dataset-sha"
    assert metadata["hydrated_dataset_sha256"] == "hydrated-sha"
    assert metadata["source_dataset_sha256"] == "source-sha"
    assert metadata["evaluated_subset_sha256"] == "subset-sha"
    assert metadata["question_count"] == 1
    assert metadata["task_type_counts"] == {"semantic_screen": 1}
    assert metadata["issuer_ks"] == [1, 3, 5]
    assert metadata["document_count"] == 3_195
    assert metadata["chunk_count"] == 3_030_425
    assert metadata["embedding_count"] == 3_030_425
    assert metadata["embedding_dimensions"] == 512
    assert metadata["semantic_candidate_limits"] == [50]
    assert metadata["result_limits"] == [25]
