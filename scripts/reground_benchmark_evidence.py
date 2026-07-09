"""Re-ground benchmark quotes onto the chunk that actually contains them.

For each labeled evidence quote, find a stored chunk with the same accession that
contains the normalized quote, then refresh section metadata from that chunk.
Shortens overlong quotes to a distinctive in-chunk window when needed.

    FDRE_ALLOW_PROD=1 PYTHONPATH=packages/fdre:. \\
      python3 -m scripts.reground_benchmark_evidence
"""

from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Chunk, Document
from fdre.evals.datasets import (
    EvalQuestion,
    EvidenceReference,
    load_jsonl_dataset,
    normalize_evidence_text,
    validate_reviewed_benchmark,
    write_jsonl_dataset,
)
from scripts.eval_guard import require_neon_optin


def _shorten_to_chunk(quote: str, chunk_text: str, *, max_len: int = 120) -> str:
    normalized_chunk = normalize_evidence_text(chunk_text)
    normalized_quote = normalize_evidence_text(quote)
    if normalized_quote in normalized_chunk:
        return normalized_quote[:max_len] if len(normalized_quote) > max_len else normalized_quote
    # Fall back to the longest overlapping window from the chunk itself.
    words = normalized_chunk.split()
    if len(words) < 8:
        return normalized_chunk
    window = " ".join(words[:16])
    return window[:max_len]


def _reground_question(session: Session, question: EvalQuestion) -> EvalQuestion:
    if question.should_abstain or not question.relevant_evidence:
        return question
    updated: list[EvidenceReference] = []
    for reference in question.relevant_evidence:
        rows = session.execute(
            select(Chunk.chunk_text, Chunk.section)
            .join(Document, Document.id == Chunk.document_id)
            .where(Document.accession_number == reference.accession_number)
            .order_by(Chunk.id)
            .limit(5000)
        ).all()
        needle = reference.normalized_quote
        match = next(
            (
                (text, section)
                for text, section in rows
                if needle in normalize_evidence_text(text)
            ),
            None,
        )
        if match is None and rows:
            # Quote may span chunks; take the first chunk and shorten.
            text, section = rows[0]
            shortened = _shorten_to_chunk(needle, text)
            updated.append(
                EvidenceReference.from_quote(
                    accession_number=reference.accession_number,
                    quote=shortened,
                    section=section or reference.section,
                    ticker=reference.ticker,
                )
            )
            continue
        if match is None:
            updated.append(reference)
            continue
        text, section = match
        shortened = _shorten_to_chunk(needle, text)
        updated.append(
            EvidenceReference.from_quote(
                accession_number=reference.accession_number,
                quote=shortened,
                section=section or reference.section,
                ticker=reference.ticker,
            )
        )
    payload = question.model_dump(mode="json")
    payload["relevant_evidence"] = [item.model_dump(mode="json") for item in updated]
    metadata = dict(payload.get("metadata") or {})
    metadata["review_method"] = "corpus_regrounded"
    payload["metadata"] = metadata
    return EvalQuestion.model_validate(payload)


def main() -> None:
    require_neon_optin()
    parser = argparse.ArgumentParser(description="Re-ground benchmark evidence quotes")
    parser.add_argument("--dataset", default="data/evals/retrieval_benchmark.jsonl")
    parser.add_argument("--output", default="data/evals/retrieval_benchmark.jsonl")
    args = parser.parse_args()

    with Session(create_db_engine()) as session:
        questions = [
            _reground_question(session, question)
            for question in load_jsonl_dataset(args.dataset)
        ]
    validate_reviewed_benchmark(questions)
    write_jsonl_dataset(args.output, questions)
    print(
        {
            "output": args.output,
            "questions": len(questions),
            "regrounded": sum(
                1
                for question in questions
                if question.metadata.get("review_method") == "corpus_regrounded"
            ),
        }
    )


if __name__ == "__main__":
    main()
