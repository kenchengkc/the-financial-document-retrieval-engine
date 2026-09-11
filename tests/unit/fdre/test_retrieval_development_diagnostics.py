from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import scripts.benchmarks.retrieval_development_diagnostics as diagnostics_cli
from sqlalchemy.orm import Session

from fdre.evals.datasets import EvalQuestion, EvidenceReference
from fdre.evals.retrieval_diagnostics import (
    build_retrieval_development_diagnostic,
    summarize_retrieval_development_diagnostics,
    write_retrieval_development_diagnostics,
)
from fdre.retrieval.query import RetrievalCandidate, SearchFilters


def _question(*, answer_type: str = "text") -> EvalQuestion:
    return EvalQuestion(
        question_id="development-test",
        question="What does FICO say about export controls?",
        split="development",
        category="narrative",
        answer_type=answer_type,
        expected_tickers=["FICO"],
        expected_sections=["Business"],
        relevant_evidence=[
            EvidenceReference.from_quote(
                accession_number="0000814547-21-000019",
                section="Business",
                quote="laws regarding export controls",
                ticker="FICO",
            )
        ],
    )


def _candidate(
    chunk_id: int,
    *,
    text: str,
    accession: str = "0000814547-21-000019",
    section: str = "Business",
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        text=text,
        metadata={
            "accession_number": accession,
            "section": section,
            "ticker": "FICO",
        },
    )


def test_diagnostic_separates_false_scope_candidate_miss_and_rerank_loss() -> None:
    question = _question()
    relevant = _candidate(1, text="The filing discusses laws regarding export controls.")
    distractor = _candidate(2, text="Unrelated disclosure.", accession="other")

    diagnostic = build_retrieval_development_diagnostic(
        question,
        inferred_tickers=["FICO", "PFG"],
        inferred_sections=["Business", "Controls and Procedures"],
        candidate_pool=[distractor, relevant],
        final_candidates=[distractor],
        final_k=1,
        stage_timings_ms={"dense": 10.0, "rerank": 2.0},
        estimated_embedding_tokens=12,
        reranker_candidate_count=2,
    )

    assert diagnostic.unexpected_tickers == ("PFG",)
    assert diagnostic.unexpected_sections == ("Controls and Procedures",)
    assert diagnostic.candidate_recall == 1.0
    assert diagnostic.final_recall == 0.0
    assert diagnostic.candidate_miss is False
    assert diagnostic.rerank_loss is True


def test_diagnostic_summary_breaks_out_table_losses() -> None:
    relevant = _candidate(1, text="The filing discusses laws regarding export controls.")
    table_question = _question(answer_type="table")
    text_question = _question()

    table = build_retrieval_development_diagnostic(
        table_question,
        inferred_tickers=["FICO"],
        inferred_sections=[],
        candidate_pool=[],
        final_candidates=[],
        final_k=10,
        stage_timings_ms={"dense": 5.0, "rerank": 1.0},
        estimated_embedding_tokens=10,
        reranker_candidate_count=0,
    )
    text = build_retrieval_development_diagnostic(
        text_question,
        inferred_tickers=["FICO"],
        inferred_sections=["Business"],
        candidate_pool=[relevant],
        final_candidates=[relevant],
        final_k=10,
        stage_timings_ms={"dense": 15.0, "rerank": 3.0},
        estimated_embedding_tokens=20,
        reranker_candidate_count=1,
    )

    summary = summarize_retrieval_development_diagnostics(
        [table, text],
        final_k=10,
    )

    assert summary["candidate_miss_count"] == 1
    assert summary["rerank_loss_count"] == 0
    assert summary["table_questions"]["candidate_miss_count"] == 1
    assert summary["stage_latency_ms"]["dense"] == {"p50": 10.0, "p95": 15.0}
    assert summary["provider_usage"] == {
        "embedding_query_calls": 2,
        "estimated_embedding_tokens": 30,
        "reranker_calls": 1,
        "reranker_candidate_documents": 1,
    }


def test_write_diagnostics_binds_benchmark_metadata(tmp_path: Path) -> None:
    diagnostic = build_retrieval_development_diagnostic(
        _question(),
        inferred_tickers=["FICO"],
        inferred_sections=["Business"],
        candidate_pool=[],
        final_candidates=[],
        final_k=10,
        stage_timings_ms={},
        estimated_embedding_tokens=8,
        reranker_candidate_count=0,
    )

    json_path, markdown_path = write_retrieval_development_diagnostics(
        tmp_path,
        [diagnostic],
        benchmark_metadata={
            "dataset_sha256": "abc123",
            "git_sha": "deadbeef",
            "corpus_snapshot_id": "snapshot",
        },
        final_k=10,
    )

    payload = json.loads(json_path.read_text())
    assert payload["schema_version"] == "fdre-retrieval-development-diagnostics-v1"
    assert payload["benchmark"]["dataset_sha256"] == "abc123"
    assert payload["benchmark"]["git_sha"] == "deadbeef"
    assert "development-only diagnostic evidence" in markdown_path.read_text()


class FakeHybrid:
    def search(
        self,
        _session: Session,
        _query: str,
        *,
        filters: SearchFilters,
        limit: int,
        timings_ms: dict[str, int],
    ) -> list[RetrievalCandidate]:
        assert filters.tickers == ["FICO"]
        assert filters.sections == ["Business"]
        assert limit == 3
        timings_ms.update({"embedding": 2, "dense": 4, "sparse": 3, "fusion": 1})
        return [
            _candidate(1, text="The filing discusses laws regarding export controls."),
            _candidate(2, text="Other text.", accession="other"),
        ]


class FakeReranker:
    def rerank(
        self,
        _query: str,
        candidates: list[RetrievalCandidate],
        *,
        top_n: int,
    ) -> list[RetrievalCandidate]:
        assert top_n == 1
        return candidates[:top_n]


def test_development_command_collects_query_only_scope_and_stage_timings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(rerank_top_n=3)
    monkeypatch.setattr(diagnostics_cli, "get_settings", lambda: settings)
    monkeypatch.setattr(
        diagnostics_cli,
        "embedding_provider_from_settings",
        lambda _settings: object(),
    )
    monkeypatch.setattr(diagnostics_cli, "DenseRetriever", lambda _provider: object())
    monkeypatch.setattr(diagnostics_cli, "SparseRetriever", lambda: object())
    monkeypatch.setattr(
        diagnostics_cli,
        "HybridRetriever",
        lambda _dense, _sparse: FakeHybrid(),
    )
    monkeypatch.setattr(
        diagnostics_cli,
        "reranker_from_settings",
        lambda _settings: FakeReranker(),
    )
    monkeypatch.setattr(diagnostics_cli, "load_company_references", lambda _session: [])

    def fake_preprocess(
        _query: str,
        *,
        companies: list[object],
        filters: SearchFilters | None = None,
    ) -> SimpleNamespace:
        del companies
        if filters is None:
            filters = SearchFilters(
                tickers=["FICO", "PFG"],
                sections=["Controls and Procedures"],
            )
        return SimpleNamespace(filters=filters)

    monkeypatch.setattr(diagnostics_cli, "preprocess_query", fake_preprocess)

    result = diagnostics_cli.run_development_diagnostics(
        cast(Session, object()),
        questions=[_question()],
        final_k=1,
    )

    assert len(result) == 1
    assert result[0].unexpected_tickers == ("PFG",)
    assert result[0].unexpected_sections == ("Controls and Procedures",)
    assert result[0].candidate_recall == 1.0
    assert result[0].final_recall == 1.0
    assert result[0].stage_timings_ms["embedding"] == 2.0
    assert result[0].reranker_candidate_count == 2
