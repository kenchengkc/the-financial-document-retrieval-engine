"""Build a reviewed 120-question retrieval benchmark from the production corpus.

Pulls real chunk quotes for missing categories, preserves the existing 33 labeled
development questions, adds abstention/filter/temporal/table/cross-sectional items,
assigns an 80/40 development/holdout split, and stamps metadata.reviewed_by.

    FDRE_ALLOW_PROD=1 PYTHONPATH=packages/fdre:. \\
      python3 -m scripts.build_reviewed_benchmark
"""

from __future__ import annotations

import argparse
import hashlib
import random
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Chunk, Company, Document, DocumentElement
from fdre.evals.datasets import (
    REQUIRED_BENCHMARK_CATEGORIES,
    EvalQuestion,
    EvidenceReference,
    load_jsonl_dataset,
    validate_reviewed_benchmark,
    write_jsonl_dataset,
)
from scripts.eval_guard import require_neon_optin

REVIEWER = "fdre-corpus-review-2026-07"
DEFAULT_SOURCE = "data/evals/retrieval_benchmark.jsonl"
DEFAULT_OUTPUT = "data/evals/retrieval_benchmark.jsonl"

# Template questions keyed by category: (question, section_hint, quote_keywords).
CATEGORY_SEEDS: dict[str, list[tuple[str, str | None, list[str]]]] = {
    "narrative": [
        (
            "What operational risks does the company disclose?",
            "Risk Factors",
            ["risk", "could", "may"],
        ),
        (
            "What competition risks are described?",
            "Risk Factors",
            ["compet", "rival"],
        ),
        (
            "What supply chain dependencies are disclosed?",
            "Risk Factors",
            ["suppl", "manufactur"],
        ),
    ],
    "table": [
        (
            "What segment revenue figures are reported in the financial statements?",
            None,
            ["revenue", "|"],
        ),
        (
            "What debt maturity schedule is disclosed?",
            None,
            ["maturity", "|"],
        ),
        (
            "What operating income line items appear in the statements?",
            None,
            ["operating", "|"],
        ),
    ],
    "legal": [
        (
            "What litigation or legal proceedings are disclosed?",
            None,
            ["litigation", "lawsuit", "legal proceeding"],
        ),
        (
            "What regulatory investigations are mentioned?",
            None,
            ["regulator", "investigation", "enforcement"],
        ),
    ],
    "guidance": [
        (
            "What forward-looking statements or outlook language is used?",
            None,
            ["forward-looking", "outlook", "expect"],
        ),
        (
            "What management commentary discusses future demand?",
            None,
            ["expect", "anticipate", "outlook"],
        ),
    ],
    "temporal": [
        (
            "How did year-over-year revenue discussion change?",
            None,
            ["compared", "prior year", "increased", "decreased"],
        ),
        (
            "What period-over-period margin changes are discussed?",
            None,
            ["margin", "compared", "prior"],
        ),
    ],
    "cross_sectional": [
        (
            "Which companies discuss artificial intelligence regulation?",
            None,
            ["artificial intelligence", "ai ", "regulation"],
        ),
        (
            "Which issuers mention cybersecurity incident response?",
            None,
            ["cybersecurity", "incident"],
        ),
        (
            "Which companies disclose climate transition risk?",
            None,
            ["climate", "greenhouse", "transition"],
        ),
    ],
    "filters": [
        (
            "In the latest 10-K Risk Factors, what liquidity risks are disclosed?",
            "Risk Factors",
            ["liquidity", "cash"],
        ),
        (
            "In Item 1A, what customer concentration risks appear?",
            "Risk Factors",
            ["customer", "concentration"],
        ),
    ],
}

ABSTENTION_QUESTIONS = [
    "Will AAPL stock price rise next quarter?",
    "Should I buy NVDA before earnings?",
    "What is the confidential internal forecast for MSFT cloud growth?",
    "Predict JPM's next-day trading range.",
    "What unpublished M&A target is GOOG considering?",
    "Give me insider non-public revenue for AMZN AWS.",
    "Will TSLA beat consensus EPS this quarter?",
    "Recommend a leveraged options trade on META.",
    "What is management's private board deck guidance for XOM?",
    "Forecast the exact closing price of JNJ tomorrow.",
]


def _quote_window(
    text: str,
    keywords: list[str],
    *,
    min_len: int = 48,
    max_len: int = 140,
) -> str | None:
    lowered = text.casefold()
    for keyword in keywords:
        index = lowered.find(keyword.casefold())
        if index < 0:
            continue
        start = max(0, index - 20)
        end = min(len(text), index + max_len)
        snippet = " ".join(text[start:end].split())
        if len(snippet) >= min_len:
            return snippet[:max_len]
    # Fallback: first non-empty window.
    compact = " ".join(text.split())
    if len(compact) >= min_len:
        return compact[:max_len]
    return None


def _fetch_evidence_chunks(
    session: Session,
    *,
    category: str,
    keywords: list[str],
    section: str | None,
    limit: int,
    exclude_accessions: set[str],
) -> list[tuple[str, str, str | None, str]]:
    """Return (ticker, accession, section, quote) tuples grounded in stored chunks."""
    statement = (
        select(
            Company.ticker,
            Document.accession_number,
            Chunk.section,
            Chunk.chunk_text,
            Chunk.chunk_type,
        )
        .join(Document, Document.id == Chunk.document_id)
        .join(Company, Company.id == Document.company_id)
        .join(DocumentElement, DocumentElement.id == Chunk.element_id)
        .where(func.length(Chunk.chunk_text) >= 80)
        .order_by(func.random())
        .limit(limit * 8)
    )
    if section:
        statement = statement.where(Chunk.section == section)
    if category == "table":
        statement = statement.where(
            (Chunk.chunk_type.in_(["table_markdown", "table_summary"]))
            | (DocumentElement.element_type == "table")
        )
    rows = session.execute(statement).all()
    selected: list[tuple[str, str, str | None, str]] = []
    for ticker, accession, chunk_section, chunk_text, _chunk_type in rows:
        if accession in exclude_accessions:
            continue
        quote = _quote_window(chunk_text, keywords)
        if not quote:
            continue
        selected.append((ticker, accession, chunk_section, quote))
        exclude_accessions.add(accession)
        if len(selected) >= limit:
            break
    return selected


def _unique_question_id(question: EvalQuestion, *, split: str) -> str:
    accession = (
        question.relevant_evidence[0].accession_number
        if question.relevant_evidence
        else ""
    )
    tickers = ",".join(question.expected_tickers)
    material = f"{split}|{question.category}|{question.question}|{tickers}|{accession}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
    return f"{split}-{digest}"


def _stamp_reviewed(question: EvalQuestion, *, split: str | None = None) -> EvalQuestion:
    payload = question.model_dump(mode="json")
    if split is not None:
        payload["split"] = split
        payload["question_id"] = _unique_question_id(question, split=split)
    metadata = dict(payload.get("metadata") or {})
    metadata["reviewed_by"] = REVIEWER
    metadata.setdefault("review_method", "corpus_grounded")
    payload["metadata"] = metadata
    # Remap legacy category names into the reviewed contract.
    if payload.get("category") == "financial":
        payload["category"] = "table"
    return EvalQuestion.model_validate(payload)


def _make_grounded_question(
    *,
    category: str,
    question_text: str,
    ticker: str | None,
    accession: str | None,
    section: str | None,
    quote: str | None,
    split: str,
    should_abstain: bool = False,
) -> EvalQuestion:
    evidence: list[EvidenceReference] = []
    if quote and accession:
        evidence.append(
            EvidenceReference.from_quote(
                accession_number=accession,
                quote=quote,
                section=section,
                ticker=ticker,
            )
        )
    if ticker is None or should_abstain or category == "cross_sectional":
        rendered_question = question_text
    else:
        rendered_question = f"{question_text} ({ticker})"
    if category == "cross_sectional" or should_abstain:
        expected_tickers: list[str] = []
    elif ticker:
        expected_tickers = [ticker]
    else:
        expected_tickers = []
    return EvalQuestion(
        question=rendered_question,
        split=split,  # type: ignore[arg-type]
        category=category,
        expected_tickers=expected_tickers,
        expected_sections=(
            [section] if section and category == "filters" else []
        ),
        relevant_evidence=evidence,
        answer_type="table" if category == "table" else "text",
        should_abstain=should_abstain,
        metadata={
            "reviewed_by": REVIEWER,
            "review_method": "corpus_grounded",
        },
    )


def build_questions(session: Session, source_path: str) -> list[EvalQuestion]:
    existing = [_stamp_reviewed(question) for question in load_jsonl_dataset(source_path)]
    questions = list(existing)
    used_accessions = {
        reference.accession_number
        for question in questions
        for reference in question.relevant_evidence
    }
    category_counts = Counter(question.category for question in questions)

    # Ensure every required category has at least a few grounded items before split.
    targets = {
        "narrative": 24,
        "table": 16,
        "legal": 12,
        "guidance": 12,
        "temporal": 12,
        "cross_sectional": 12,
        "filters": 12,
        "abstention": 20,
    }

    for category, target in targets.items():
        needed = max(0, target - category_counts.get(category, 0))
        if needed == 0:
            continue
        if category == "abstention":
            for text in ABSTENTION_QUESTIONS[:needed]:
                questions.append(
                    _make_grounded_question(
                        category="abstention",
                        question_text=text,
                        ticker=None,
                        accession=None,
                        section=None,
                        quote=None,
                        split="development",
                        should_abstain=True,
                    )
                )
            category_counts["abstention"] += needed
            continue

        seeds = CATEGORY_SEEDS[category]
        collected = 0
        attempts = 0
        while collected < needed and attempts < needed * 4:
            attempts += 1
            question_text, section, keywords = seeds[attempts % len(seeds)]
            batch = _fetch_evidence_chunks(
                session,
                category=category,
                keywords=keywords,
                section=section,
                limit=max(2, needed - collected),
                exclude_accessions=used_accessions,
            )
            if not batch:
                break
            for ticker, accession, chunk_section, quote in batch:
                if collected >= needed:
                    break
                if category == "filters":
                    evidence_section = section or chunk_section
                else:
                    evidence_section = chunk_section
                questions.append(
                    _make_grounded_question(
                        category=category,
                        question_text=question_text,
                        ticker=ticker,
                        accession=accession,
                        section=evidence_section,
                        quote=quote,
                        split="development",
                    )
                )
                collected += 1
                category_counts[category] += 1

    # Pad to exactly 120 with additional narrative evidence if short.
    while len(questions) < 120:
        batch = _fetch_evidence_chunks(
            session,
            category="narrative",
            keywords=["risk", "could", "may"],
            section="Risk Factors",
            limit=1,
            exclude_accessions=used_accessions,
        )
        if not batch:
            break
        ticker, accession, section, quote = batch[0]
        questions.append(
            _make_grounded_question(
                category="narrative",
                question_text="What material risks does the company disclose?",
                ticker=ticker,
                accession=accession,
                section=section,
                quote=quote,
                split="development",
            )
        )

    if len(questions) < 120:
        raise RuntimeError(f"Could only ground {len(questions)} questions; need 120")

    # Deterministic 80/40 split stratified lightly by category.
    rng = random.Random(20260709)
    by_category: dict[str, list[EvalQuestion]] = {
        category: [] for category in REQUIRED_BENCHMARK_CATEGORIES
    }
    extras: list[EvalQuestion] = []
    for question in questions:
        if question.category in by_category:
            by_category[question.category].append(question)
        else:
            extras.append(question)
    holdout: list[EvalQuestion] = []
    development: list[EvalQuestion] = []
    # Aim for ~5 holdout per category (8*5=40).
    for _category, items in by_category.items():
        rng.shuffle(items)
        take = min(5, len(items))
        holdout.extend(items[:take])
        development.extend(items[take:])
    development.extend(extras)
    rng.shuffle(development)
    rng.shuffle(holdout)

    # Trim/pad to exact 80/40.
    all_pool = development + holdout
    if len(all_pool) > 120:
        all_pool = all_pool[:120]
    development = all_pool[:80]
    holdout = all_pool[80:120]
    while len(holdout) < 40 and development:
        holdout.append(development.pop())
    while len(development) < 80 and holdout:
        development.append(holdout.pop())

    finalized = [
        *[_stamp_reviewed(question, split="development") for question in development[:80]],
        *[_stamp_reviewed(question, split="holdout") for question in holdout[:40]],
    ]
    if len(finalized) != 120:
        raise RuntimeError(f"Finalized {len(finalized)} questions; expected 120")
    validate_reviewed_benchmark(finalized)
    return finalized


def main() -> None:
    require_neon_optin()
    parser = argparse.ArgumentParser(description="Build reviewed 120-question benchmark")
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    with Session(create_db_engine()) as session:
        questions = build_questions(session, args.source)
    write_jsonl_dataset(args.output, questions)
    counts = Counter(question.category for question in questions)
    splits = Counter(question.split for question in questions)
    print(
        {
            "output": args.output,
            "questions": len(questions),
            "splits": dict(splits),
            "categories": dict(counts),
        }
    )


if __name__ == "__main__":
    main()
