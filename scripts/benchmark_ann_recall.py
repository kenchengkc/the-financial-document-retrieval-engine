"""Exact-versus-ANN dense Recall@k on a ticker-filtered sample.

Exact search disables index scans and ranks by halfvec cosine distance in SQL.
ANN uses the production HNSW path in DenseRetriever. Both share the same Voyage
query embedding.

    FDRE_ALLOW_PROD=1 PYTHONPATH=packages/fdre:. python3 -m scripts.benchmark_ann_recall
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import cast, select, text
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import create_db_engine
from apps.api.app.models import Chunk, Company, Document, Embedding
from fdre.evals.metrics import recall_at_k
from fdre.indexing.embeddings import embedding_provider_from_settings
from fdre.retrieval.dense import DenseRetriever
from fdre.retrieval.query import SearchFilters
from scripts.eval_guard import require_neon_optin

DEFAULT_QUERIES = [
    ("AAPL", "supply chain manufacturing inventory risk"),
    ("MSFT", "cybersecurity incident response training"),
    ("NVDA", "export control advanced semiconductor China"),
    ("JPM", "credit risk allowance for credit losses"),
    ("XOM", "climate transition greenhouse gas emissions"),
    ("AMZN", "fulfillment capacity warehouse labor"),
    ("GOOG", "antitrust competition regulatory proceedings"),
    ("META", "content moderation advertising revenue"),
    ("LLY", "clinical trial pharmaceutical pipeline"),
    ("JNJ", "product liability litigation medical device"),
]


def _exact_top_ids(
    session: Session,
    *,
    ticker: str,
    query_vector: list[float],
    provider_name: str,
    provider_model: str,
    dimensions: int,
    k: int,
) -> list[int]:
    # Disable index access so Postgres ranks the filtered set exactly.
    session.execute(text("SET LOCAL enable_indexscan = off"))
    session.execute(text("SET LOCAL enable_bitmapscan = off"))
    session.execute(text("SET LOCAL enable_indexonlyscan = off"))
    distance = cast(Embedding.vector, HALFVEC(dimensions)).cosine_distance(query_vector)
    rows = session.execute(
        select(Chunk.id)
        .join(Embedding, Embedding.chunk_id == Chunk.id)
        .join(Document, Document.id == Chunk.document_id)
        .join(Company, Company.id == Document.company_id)
        .where(
            Company.ticker == ticker,
            Embedding.provider == provider_name,
            Embedding.model == provider_model,
            Embedding.dimensions == dimensions,
        )
        .order_by(distance, Chunk.id)
        .limit(k)
    ).all()
    session.execute(text("RESET enable_indexscan"))
    session.execute(text("RESET enable_bitmapscan"))
    session.execute(text("RESET enable_indexonlyscan"))
    return [int(row[0]) for row in rows]


def main() -> None:
    require_neon_optin()
    parser = argparse.ArgumentParser(description="Measure exact-versus-ANN Recall@k")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--output", default="data/processed/evals/ann_recall_benchmark.json")
    args = parser.parse_args()

    settings = get_settings()
    provider = embedding_provider_from_settings(settings)
    dense = DenseRetriever(provider)
    deltas: list[float] = []
    rows: list[dict[str, object]] = []

    with Session(create_db_engine()) as session:
        for ticker, question in DEFAULT_QUERIES:
            with session.begin():
                query_vector = provider.embed_texts([question], input_type="query")[0]
                exact_ids = _exact_top_ids(
                    session,
                    ticker=ticker,
                    query_vector=query_vector,
                    provider_name=provider.name,
                    provider_model=provider.model,
                    dimensions=provider.dimensions,
                    k=args.k,
                )
                ann_candidates = dense.search(
                    session,
                    question,
                    filters=SearchFilters(tickers=[ticker]),
                    limit=args.k,
                )
                ann_ids = [candidate.chunk_id for candidate in ann_candidates]
                relevant = set(exact_ids)
                recall = recall_at_k(ann_ids, relevant, args.k)
                delta = 1.0 - recall
                deltas.append(delta)
                rows.append(
                    {
                        "ticker": ticker,
                        "question": question,
                        "exact_ids": exact_ids,
                        "ann_ids": ann_ids,
                        "ann_recall_at_k": recall,
                        "delta_from_exact": delta,
                    }
                )

    mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
    max_delta = max(deltas) if deltas else 0.0
    report = {
        "k": args.k,
        "query_count": len(rows),
        "mean_ann_recall_at_k": 1.0 - mean_delta,
        "mean_delta_from_exact": mean_delta,
        "max_delta_from_exact": max_delta,
        "gate_max_delta": 0.02,
        "pass": max_delta <= 0.02,
        "queries": rows,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in report if key != "queries"}, indent=2))
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
