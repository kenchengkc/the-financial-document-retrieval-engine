from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import create_db_engine
from apps.api.app.models import Chunk, Company, Document, DocumentElement, Embedding
from fdre.chunking import rebuild_document_chunks
from fdre.evals.datasets import EvalQuestion, load_jsonl_dataset
from fdre.evals.runner import VariantMetrics, evaluate_variants, write_eval_report
from fdre.indexing.embeddings import (
    EmbeddingProvider,
    embedding_provider_from_settings,
    rebuild_embeddings,
)
from fdre.parsing.html_filing_parser import HtmlFilingParser
from fdre.retrieval.dense import DenseRetriever
from fdre.retrieval.hybrid import HybridRetriever
from fdre.retrieval.preprocess import load_company_references, preprocess_query
from fdre.retrieval.query import RetrievalCandidate, SearchFilters
from fdre.retrieval.rerank import reranker_from_name
from fdre.retrieval.sparse import SparseRetriever


def chunk_selected_documents(
    session: Session,
    *,
    tickers: list[str] | None,
    max_tokens: int,
) -> tuple[int, int]:
    statement = select(Document).join(Document.company).order_by(Document.id)
    if tickers:
        statement = statement.where(Company.ticker.in_([ticker.upper() for ticker in tickers]))
    documents = list(session.scalars(statement))

    chunk_count = 0
    for document in documents:
        chunk_count += len(
            rebuild_document_chunks(session, document.id, max_tokens=max_tokens)
        )
    return len(documents), chunk_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build FDRE retrieval artifacts")
    subparsers = parser.add_subparsers(dest="command", required=True)
    chunk_parser = subparsers.add_parser("chunk", help="Rebuild document chunks")
    chunk_parser.add_argument("--tickers", nargs="+")
    chunk_parser.add_argument("--max-tokens", type=int, default=220)
    subparsers.add_parser("index", help="Rebuild stored chunk embeddings")
    eval_parser = subparsers.add_parser("eval", help="Run retrieval evaluation")
    eval_parser.add_argument("dataset")
    eval_parser.add_argument("--output-dir", default="data/processed/evals")
    eval_parser.add_argument("--k", type=int, default=5)
    subparsers.add_parser(
        "seed-demo",
        help="Load the checked-in sample filing and build its retrieval artifacts",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with Session(create_db_engine()) as session:
        if args.command == "chunk":
            documents, chunks = chunk_selected_documents(
                session,
                tickers=args.tickers,
                max_tokens=args.max_tokens,
            )
            print({"documents": documents, "chunks": chunks})
        elif args.command == "index":
            provider = embedding_provider_from_settings(get_settings())
            print({"embeddings": rebuild_embeddings(session, provider)})
        elif args.command == "eval":
            metrics = run_retrieval_eval(
                session,
                questions=load_jsonl_dataset(args.dataset),
                k=args.k,
            )
            paths = write_eval_report(args.output_dir, metrics, k=args.k)
            print({"json": str(paths[0]), "markdown": str(paths[1])})
        elif args.command == "seed-demo":
            print(seed_demo_document(session))


def seed_demo_document(
    session: Session,
    *,
    fixture_path: Path | None = None,
    provider: EmbeddingProvider | None = None,
) -> dict[str, int]:
    path = fixture_path or Path("data/sample/sec_filing.html")
    company = session.scalar(select(Company).where(Company.ticker == "EXMPL"))
    if company is None:
        company = Company(
            ticker="EXMPL",
            cik="0000000001",
            name="Example Company",
            exchange="SAMPLE",
        )
        session.add(company)
        session.flush()

    document = session.scalar(
        select(Document).where(
            Document.company_id == company.id,
            Document.accession_number == "0000000001-25-000001",
        )
    )
    if document is None:
        document = Document(
            company=company,
            source_type="sample",
            form_type="10-K",
            filing_date=date(2025, 12, 31),
            accession_number="0000000001-25-000001",
            source_url="data/sample/sec_filing.html",
            local_path=str(path),
        )
        session.add(document)
        session.flush()
    else:
        chunk_ids = select(Chunk.id).where(Chunk.document_id == document.id)
        session.execute(delete(Embedding).where(Embedding.chunk_id.in_(chunk_ids)))
        session.execute(delete(Chunk).where(Chunk.document_id == document.id))
        session.execute(
            delete(DocumentElement).where(DocumentElement.document_id == document.id)
        )

    parsed = HtmlFilingParser().parse_file(path)
    session.add_all(
        [
            DocumentElement(
                document_id=document.id,
                element_type=element.element_type,
                page_number=element.page_number,
                section=element.section,
                text=element.text,
                markdown=element.markdown,
                json_payload=element.metadata,
                bbox=element.bbox,
                reading_order=element.reading_order,
            )
            for element in parsed
        ]
    )
    session.commit()
    chunks = rebuild_document_chunks(session, document.id)
    embeddings = rebuild_embeddings(
        session,
        provider or embedding_provider_from_settings(get_settings()),
        chunk_ids=[chunk.id for chunk in chunks],
    )
    return {
        "documents": 1,
        "elements": len(parsed),
        "chunks": len(chunks),
        "embeddings": embeddings,
    }


def run_retrieval_eval(
    session: Session,
    *,
    questions: list[EvalQuestion],
    k: int,
) -> list[VariantMetrics]:
    settings = get_settings()
    provider = embedding_provider_from_settings(settings)
    dense = DenseRetriever(provider)
    sparse = SparseRetriever()
    hybrid = HybridRetriever(dense, sparse)
    companies = load_company_references(session)

    def retrieve(question: EvalQuestion, variant: str) -> list[RetrievalCandidate]:
        preprocessed = preprocess_query(
            question.question,
            companies=companies,
            filters=SearchFilters(
                tickers=question.expected_tickers,
                sections=question.expected_sections,
            ),
        )
        if variant == "dense":
            return dense.search(
                session,
                question.question,
                filters=preprocessed.filters,
                limit=k,
            )
        if variant == "sparse":
            return sparse.search(
                session,
                question.question,
                filters=preprocessed.filters,
                limit=k,
            )
        candidates = hybrid.search(
            session,
            question.question,
            filters=preprocessed.filters,
            limit=max(k, settings.rerank_top_n),
        )
        if variant == "hybrid":
            return candidates[:k]
        return reranker_from_name(settings.reranker_provider).rerank(
            question.question,
            candidates,
            top_n=k,
        )

    return evaluate_variants(
        questions,
        {
            "Dense only": lambda question: retrieve(question, "dense"),
            "Sparse only": lambda question: retrieve(question, "sparse"),
            "Hybrid": lambda question: retrieve(question, "hybrid"),
            "Hybrid + reranker": lambda question: retrieve(question, "rerank"),
        },
        k=k,
    )


if __name__ == "__main__":
    main()
