"""Before/after retrieval benchmark for the multi-query / fusion upgrades.

Runs the labeled query set in ``data/evals/retrieval_benchmark.jsonl`` through a
"baseline" retriever (single query, weighted fusion, ts_rank) and the shipped
default (multi-query expansion, weighted fusion, ts_rank) and prints recall@k,
MRR and nDCG@k for each. The labels are content-grounded: a retrieved chunk is
relevant only if it shares the issuer + section and contains the labeled quote.

    PYTHONPATH=packages/fdre:. python3.11 -m scripts.benchmark_retrieval
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import create_db_engine
from fdre.evals.datasets import EvalQuestion
from fdre.evals.runner import evaluate_variants
from fdre.indexing.embeddings import embedding_provider_from_settings
from fdre.retrieval.dense import DenseRetriever
from fdre.retrieval.hybrid import HybridRetriever
from fdre.retrieval.preprocess import CompanyReference, load_company_references, preprocess_query
from fdre.retrieval.query import RetrievalCandidate, SearchFilters
from fdre.retrieval.sparse import SparseRetriever

DEFAULT_DATASET = "data/evals/retrieval_benchmark.jsonl"


def _make_retriever(
    session: Session,
    companies: list[CompanyReference],
    hybrid: HybridRetriever,
    *,
    multi_query: bool,
    k: int,
) -> Callable[[EvalQuestion], list[RetrievalCandidate]]:
    def retrieve(question: EvalQuestion) -> list[RetrievalCandidate]:
        pre = preprocess_query(
            question.question,
            companies=companies,
            filters=SearchFilters(
                tickers=question.expected_tickers,
                sections=question.expected_sections,
            ),
        )
        queries = pre.rewritten_queries[1:] if multi_query else None
        return hybrid.search(
            session, question.question, filters=pre.filters, limit=k, queries=queries
        )

    return retrieve


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    questions = [
        EvalQuestion.model_validate_json(line)
        for line in Path(args.dataset).read_text().splitlines()
        if line.strip()
    ]
    settings = get_settings()
    dense = DenseRetriever(embedding_provider_from_settings(settings))
    hybrid = HybridRetriever(dense, SparseRetriever())  # shipped defaults

    engine = create_db_engine()
    with Session(engine) as session:
        companies = load_company_references(session)
        metrics = evaluate_variants(
            questions,
            {
                "Baseline (single query)": _make_retriever(
                    session, companies, hybrid, multi_query=False, k=args.k
                ),
                "Shipped (multi-query expansion)": _make_retriever(
                    session, companies, hybrid, multi_query=True, k=args.k
                ),
            },
            k=args.k,
        )

    print(f"\n{len(questions)} labeled queries | metrics @k={args.k}\n")
    print(f"{'variant':<34} {'recall':>7} {'MRR':>7} {'nDCG':>7}")
    print("-" * 58)
    for metric in metrics:
        print(
            f"{metric.variant:<34} {metric.recall_at_k:>7.3f} "
            f"{metric.mrr:>7.3f} {metric.ndcg_at_k:>7.3f}"
        )
    base, ship = metrics[0], metrics[1]
    print(
        f"\nlift: recall {ship.recall_at_k - base.recall_at_k:+.3f}  "
        f"MRR {ship.mrr - base.mrr:+.3f}  nDCG {ship.ndcg_at_k - base.ndcg_at_k:+.3f}"
    )


if __name__ == "__main__":
    main()
