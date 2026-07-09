"""Remediate documents that have parsed elements but no chunks.

    FDRE_ALLOW_PROD=1 PYTHONPATH=packages/fdre:. \\
      python3 -m scripts.remediate_unchunked
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.services.operations_service import build_data_quality_report
from scripts.eval_guard import require_neon_optin
from scripts.retrieval_pipeline import chunk_selected_documents


def main() -> None:
    require_neon_optin()
    parser = argparse.ArgumentParser(description="Chunk documents missing chunks")
    parser.add_argument("--max-tokens", type=int, default=220)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List unchunked documents without writing chunks",
    )
    args = parser.parse_args()

    with Session(create_db_engine()) as session:
        before = build_data_quality_report(session)
        print(
            json.dumps(
                {
                    "documents_without_chunks": before.documents_without_chunks,
                    "unchunked_documents": [
                        item.model_dump(mode="json") for item in before.unchunked_documents
                    ],
                },
                indent=2,
            )
        )
        if args.dry_run or before.documents_without_chunks == 0:
            return

        remediable = [
            item
            for item in before.unchunked_documents
            if item.reason == "elements_present_not_chunked"
        ]
        tickers = sorted({item.ticker for item in remediable})
        if not tickers:
            print("No remediable unchunked documents (need parsed elements).")
            return

        document_count, chunk_count = chunk_selected_documents(
            session,
            tickers=tickers,
            max_tokens=args.max_tokens,
            force_rechunk=False,
        )
        session.commit()
        after = build_data_quality_report(session)
        print(
            json.dumps(
                {
                    "remediated_tickers": tickers,
                    "documents_scanned": document_count,
                    "chunks_created": chunk_count,
                    "documents_without_chunks_after": after.documents_without_chunks,
                    "unchunked_after": [
                        item.model_dump(mode="json") for item in after.unchunked_documents
                    ],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
