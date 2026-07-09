"""Stratified retrieval latency benchmark (single-name vs cross-sectional).

    FDRE_ALLOW_PROD=1 PYTHONPATH=packages/fdre:. python3 -m scripts.benchmark_latency
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import create_db_engine
from fdre.indexing.embeddings import embedding_provider_from_settings
from fdre.retrieval.dense import DenseRetriever
from fdre.retrieval.hybrid import HybridRetriever
from fdre.retrieval.preprocess import load_company_references, preprocess_query
from fdre.retrieval.query import SearchFilters
from fdre.retrieval.sparse import SparseRetriever
from scripts.eval_guard import require_neon_optin

SINGLE_NAME_QUERIES = [
    ("AAPL", "What are Apple's supply chain risks?"),
    ("MSFT", "What cybersecurity risks does Microsoft disclose?"),
    ("NVDA", "What export control risks does NVIDIA face?"),
    ("JPM", "What credit risk factors does JPMorgan discuss?"),
    ("XOM", "What climate-related risks does Exxon disclose?"),
]

CROSS_SECTIONAL_QUERIES = [
    "Which companies discuss data center power constraints?",
    "Which issuers mention artificial intelligence regulation risk?",
    "Which companies disclose cybersecurity incident response?",
    "Which filings discuss supply chain concentration risk?",
    "Which companies mention interest rate sensitivity?",
]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((pct / 100) * (len(ordered) - 1))))
    return ordered[index]


def _time_search(
    session: Session,
    hybrid: HybridRetriever,
    companies: list,
    question: str,
    *,
    tickers: list[str] | None,
    k: int,
) -> float:
    started = time.perf_counter()
    pre = preprocess_query(
        question,
        companies=companies,
        filters=SearchFilters(tickers=tickers or []),
    )
    hybrid.search(
        session,
        question,
        filters=pre.filters,
        limit=k,
        queries=pre.rewritten_queries[1:] or None,
    )
    return (time.perf_counter() - started) * 1000


def main() -> None:
    require_neon_optin()
    parser = argparse.ArgumentParser(description="Measure stratified retrieval latency")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", default="data/processed/evals/latency_benchmark.json")
    args = parser.parse_args()

    settings = get_settings()
    provider = embedding_provider_from_settings(settings)
    hybrid = HybridRetriever(DenseRetriever(provider), SparseRetriever())

    with Session(create_db_engine()) as session:
        companies = load_company_references(session)
        # Warm both filtered and unfiltered paths (planner + HNSW + Voyage).
        for _ in range(args.warmup):
            _time_search(
                session,
                hybrid,
                companies,
                SINGLE_NAME_QUERIES[0][1],
                tickers=[SINGLE_NAME_QUERIES[0][0]],
                k=args.k,
            )
            _time_search(
                session,
                hybrid,
                companies,
                CROSS_SECTIONAL_QUERIES[0],
                tickers=None,
                k=args.k,
            )

        single_latencies: list[float] = []
        for ticker, question in SINGLE_NAME_QUERIES:
            for _ in range(args.repeats):
                single_latencies.append(
                    _time_search(
                        session,
                        hybrid,
                        companies,
                        question,
                        tickers=[ticker],
                        k=args.k,
                    )
                )

        cross_latencies: list[float] = []
        for question in CROSS_SECTIONAL_QUERIES:
            for _ in range(args.repeats):
                cross_latencies.append(
                    _time_search(
                        session,
                        hybrid,
                        companies,
                        question,
                        tickers=None,
                        k=args.k,
                    )
                )

    report = {
        "k": args.k,
        "warmup": args.warmup,
        "repeats": args.repeats,
        "single_name": {
            "n": len(single_latencies),
            "p50_ms": _percentile(single_latencies, 50),
            "p95_ms": _percentile(single_latencies, 95),
            "mean_ms": statistics.fmean(single_latencies),
            "samples_ms": [round(value, 2) for value in single_latencies],
            "gate_p95_ms": 2500,
            "pass": _percentile(single_latencies, 95) < 2500,
        },
        "cross_sectional": {
            "n": len(cross_latencies),
            "p50_ms": _percentile(cross_latencies, 50),
            "p95_ms": _percentile(cross_latencies, 95),
            "mean_ms": statistics.fmean(cross_latencies),
            "samples_ms": [round(value, 2) for value in cross_latencies],
            "gate_p95_ms": 5000,
            "pass": _percentile(cross_latencies, 95) < 5000,
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
