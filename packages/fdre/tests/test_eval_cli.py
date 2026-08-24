from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdre.evals.datasets import EvalQuestion
from fdre.evals.runner import evaluate_variants_at_ks, write_multi_k_eval_report
from fdre.retrieval.query import RetrievalCandidate
from scripts import retrieval_pipeline


class FakeSearchRetriever:
    def __init__(self) -> None:
        self.limits: list[int] = []

    def search(
        self,
        *_args: object,
        limit: int,
        **_kwargs: object,
    ) -> list[RetrievalCandidate]:
        self.limits.append(limit)
        return [
            RetrievalCandidate(chunk_id=index, text=f"chunk {index}", metadata={})
            for index in range(1, limit + 1)
        ]


class FakeReranker:
    def __init__(self) -> None:
        self.top_ns: list[int] = []

    def rerank(
        self,
        _query: str,
        candidates: list[RetrievalCandidate],
        *,
        top_n: int,
    ) -> list[RetrievalCandidate]:
        self.top_ns.append(top_n)
        return candidates[:top_n]


class FakeSession:
    def __init__(self, values: list[int]) -> None:
        self.values = values

    def scalar(self, _statement: object) -> int:
        return self.values.pop(0)


def test_eval_cli_preserves_k_and_accepts_ks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["retrieval_pipeline.py", "eval", "benchmark.jsonl", "--k", "7"],
    )
    legacy = retrieval_pipeline.parse_args()
    assert legacy.k == 7
    assert legacy.ks is None

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "retrieval_pipeline.py",
            "eval",
            "benchmark.jsonl",
            "--k",
            "7",
            "--ks",
            "5",
            "10",
            "20",
        ],
    )
    multi = retrieval_pipeline.parse_args()
    assert multi.k == 7
    assert multi.ks == [5, 10, 20]


def test_run_retrieval_eval_uses_max_k_once_per_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dense = FakeSearchRetriever()
    sparse = FakeSearchRetriever()
    hybrid = FakeSearchRetriever()
    reranker = FakeReranker()
    settings = SimpleNamespace(
        rerank_top_n=50,
        reranker_provider="none",
        embedding_cost_per_million_tokens=0.0,
    )

    monkeypatch.setattr(retrieval_pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(
        retrieval_pipeline,
        "embedding_provider_from_settings",
        lambda _settings: object(),
    )
    monkeypatch.setattr(retrieval_pipeline, "DenseRetriever", lambda _provider: dense)
    monkeypatch.setattr(retrieval_pipeline, "SparseRetriever", lambda: sparse)
    monkeypatch.setattr(
        retrieval_pipeline,
        "HybridRetriever",
        lambda _dense, _sparse: hybrid,
    )
    monkeypatch.setattr(
        retrieval_pipeline,
        "load_company_references",
        lambda _session: [],
    )
    monkeypatch.setattr(
        retrieval_pipeline,
        "preprocess_query",
        lambda _question, *, companies, filters: SimpleNamespace(filters=filters),
    )
    monkeypatch.setattr(
        retrieval_pipeline,
        "reranker_from_name",
        lambda _name: reranker,
    )

    results = retrieval_pipeline.run_retrieval_eval(
        object(),
        questions=[EvalQuestion(question="test", relevant_chunk_ids=[1])],
        ks=(5, 10, 20),
    )

    assert set(results) == {5, 10, 20}
    assert dense.limits == [20]
    assert sparse.limits == [20]
    assert hybrid.limits == [50, 50]
    assert reranker.top_ns == [20]


def test_write_multi_k_eval_report(tmp_path: Path) -> None:
    candidates = [
        RetrievalCandidate(chunk_id=index, text=f"chunk {index}", metadata={})
        for index in range(1, 21)
    ]
    metrics_by_k = evaluate_variants_at_ks(
        [EvalQuestion(question="test", relevant_chunk_ids=[2, 7])],
        {"Hybrid": lambda _question: candidates},
        ks=(5, 10, 20),
    )

    json_path, markdown_path = write_multi_k_eval_report(
        tmp_path,
        metrics_by_k,
        benchmark_metadata={"dataset_sha256": "abc123"},
    )

    payload = json.loads(json_path.read_text())
    assert payload["ks"] == [5, 10, 20]
    assert payload["benchmark"]["dataset_sha256"] == "abc123"
    assert set(payload["metrics"]) == {"5", "10", "20"}

    markdown = markdown_path.read_text()
    assert "Recall@5" in markdown
    assert "Recall@10" in markdown
    assert "Recall@20" in markdown
    assert "nDCG@5" in markdown
    assert "nDCG@10" in markdown
    assert "nDCG@20" in markdown


def test_build_benchmark_metadata_records_hash_and_cutoffs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        embedding_provider="voyage",
        embedding_model="voyage-4-large",
        embedding_dimensions=512,
        reranker_provider="none",
        reranker_model="rerank-2.5",
        embedding_cost_per_million_tokens=0.12,
    )
    monkeypatch.setattr(retrieval_pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(retrieval_pipeline, "_git_sha", lambda: "deadbeef")

    metadata = retrieval_pipeline.build_benchmark_metadata(
        FakeSession([10, 20, 20]),
        dataset="benchmark.jsonl",
        dataset_sha256="abc123",
        split="development",
        question_count=80,
        ks=(5, 10, 20),
    )

    assert metadata["dataset_sha256"] == "abc123"
    assert metadata["retrieval_k"] == 20
    assert metadata["retrieval_ks"] == [5, 10, 20]
