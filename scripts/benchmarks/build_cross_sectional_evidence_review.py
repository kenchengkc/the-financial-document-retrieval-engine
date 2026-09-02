from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Chunk, Document
from fdre.evals import build_cross_sectional_screen_plan, load_jsonl_dataset
from fdre.evals.datasets import EvalQuestion
from fdre.research.panel import ResearchPanelQuery, ResearchPanelRow, build_research_panel
from scripts.benchmarks.eval_guard import require_neon_optin

DEFAULT_DATASET = "data/evals/cross_sectional_benchmark.v1.jsonl"
DEFAULT_OUTPUT = "data/processed/evals/cross-sectional-evidence-review.jsonl"
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "about",
        "and",
        "around",
        "for",
        "from",
        "into",
        "of",
        "over",
        "the",
        "their",
        "under",
        "with",
    }
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a provider-free review packet from each gold issuer's exact "
            "point-in-time screen-selected filing."
        )
    )
    parser.add_argument("dataset", nargs="?", default=DEFAULT_DATASET)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--split",
        choices=("development", "holdout", "all"),
        default="development",
    )
    parser.add_argument("--max-candidates", type=int, default=12)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.max_candidates < 1:
        raise ValueError("--max-candidates must be positive")
    require_neon_optin()

    questions = load_jsonl_dataset(args.dataset)
    if args.split != "all":
        questions = [question for question in questions if question.split == args.split]
    if not questions:
        raise ValueError(f"No benchmark questions selected for split {args.split!r}")

    engine = create_db_engine()
    with Session(engine) as session:
        records = [
            build_review_record(session, question, max_candidates=args.max_candidates)
            for question in questions
        ]

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(records)} evidence-review records to {output}")


def build_review_record(
    session: Session,
    question: EvalQuestion,
    *,
    max_candidates: int,
) -> dict[str, object]:
    if len(question.expected_tickers) != 1:
        raise ValueError(f"{question.question_id}: expected exactly one gold ticker")
    ticker = question.expected_tickers[0]
    plan = build_cross_sectional_screen_plan(question)
    if plan.tickers and ticker not in plan.tickers:
        raise ValueError(f"{question.question_id}: gold ticker is outside screen universe")

    panel = build_research_panel(
        session,
        ResearchPanelQuery(
            tickers=[ticker],
            as_of=plan.as_of,
            form_types=plan.form_types,
            sections=plan.sections,
            include_amendments=False,
            limit=1000,
        ),
    )
    if not panel.rows:
        return {
            "question_id": question.question_id,
            "ticker": ticker,
            "query": plan.semantic_query,
            "as_of": plan.as_of.isoformat(),
            "selected_accession": None,
            "candidates": [],
            "error": "no eligible PIT panel row",
        }

    selected = max(panel.rows, key=_filing_sort_key)
    query = plan.semantic_query or question.question
    terms = _query_terms(query)
    candidates = _rank_filing_chunks(
        session,
        selected.accession_number,
        terms=terms,
        max_candidates=max_candidates,
    )
    return {
        "question_id": question.question_id,
        "ticker": ticker,
        "task_type": question.resolved_task_type,
        "query": query,
        "as_of": plan.as_of.isoformat(),
        "corpus_snapshot_id": panel.corpus_snapshot_id,
        "selected_accession": selected.accession_number,
        "selected_period_end": selected.period_end.isoformat() if selected.period_end else None,
        "selected_available_at": selected.available_at.isoformat(),
        "candidates": candidates,
    }


def _rank_filing_chunks(
    session: Session,
    accession_number: str,
    *,
    terms: set[str],
    max_candidates: int,
) -> list[dict[str, object]]:
    rows = session.execute(
        select(Chunk.id, Chunk.section, Chunk.chunk_text)
        .join(Document, Document.id == Chunk.document_id)
        .where(Document.accession_number == accession_number)
        .order_by(Chunk.id)
    )
    ranked: list[tuple[int, int, str | None, str]] = []
    for chunk_id, section, text in rows:
        score = _lexical_overlap_score(terms, text)
        if score > 0:
            ranked.append((score, int(chunk_id), section, text))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [
        {
            "chunk_id": chunk_id,
            "section": section,
            "lexical_overlap": score,
            "text": text,
        }
        for score, chunk_id, section, text in ranked[:max_candidates]
    ]


def _query_terms(value: str) -> set[str]:
    return {
        token
        for token in _WORD_RE.findall(value.casefold())
        if len(token) >= 3 and token not in _STOPWORDS
    }


def _lexical_overlap_score(terms: set[str], text: str) -> int:
    if not terms:
        return 0
    text_terms = set(_WORD_RE.findall(text.casefold()))
    return len(terms & text_terms)


def _filing_sort_key(row: ResearchPanelRow) -> tuple[date, datetime, str]:
    return (row.period_end or date.min, row.available_at, row.accession_number)


if __name__ == "__main__":
    main()
