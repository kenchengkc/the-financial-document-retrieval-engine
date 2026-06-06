from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company, Document
from fdre.chunking import rebuild_document_chunks


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


if __name__ == "__main__":
    main()
