"""Refine template holdout/development questions into quote-grounded paraphrases.

Keeps evidence labels fixed. Rewrites generic template questions to mention the
issuer and a distinctive fragment of the labeled quote so retrieval matching is
more realistic.

    PYTHONPATH=packages/fdre:. python3 -m scripts.refine_benchmark_questions
"""

from __future__ import annotations

import argparse
import hashlib
import re

from fdre.evals.datasets import (
    EvalQuestion,
    load_jsonl_dataset,
    validate_reviewed_benchmark,
    write_jsonl_dataset,
)

TEMPLATE_PREFIXES = (
    "What operational risks does the company disclose?",
    "What competition risks are described?",
    "What supply chain dependencies are disclosed?",
    "What segment revenue figures are reported",
    "What debt maturity schedule is disclosed?",
    "What operating income line items appear",
    "What litigation or legal proceedings are disclosed?",
    "What regulatory investigations are mentioned?",
    "What forward-looking statements or outlook language is used?",
    "What management commentary discusses future demand?",
    "How did year-over-year revenue discussion change?",
    "What period-over-period margin changes are discussed?",
    "Which companies discuss artificial intelligence regulation?",
    "Which issuers mention cybersecurity incident response?",
    "Which companies disclose climate transition risk?",
    "In the latest 10-K Risk Factors, what liquidity risks are disclosed?",
    "In Item 1A, what customer concentration risks appear?",
    "What material risks does the company disclose?",
)


def _is_template(question: str) -> bool:
    return any(question.startswith(prefix) for prefix in TEMPLATE_PREFIXES)


def _snippet(quote: str, *, max_words: int = 12) -> str:
    words = re.findall(r"[A-Za-z0-9%-]+", quote)
    return " ".join(words[:max_words])


def _refine(question: EvalQuestion) -> EvalQuestion:
    if question.should_abstain or not question.relevant_evidence:
        return question
    if not _is_template(question.question):
        return question
    reference = question.relevant_evidence[0]
    ticker = reference.ticker or (
        question.expected_tickers[0] if question.expected_tickers else "the issuer"
    )
    snippet = _snippet(reference.normalized_quote)
    section = reference.section or "the filing"
    if question.category == "cross_sectional":
        rewritten = f"Which issuers discuss {snippet}?"
    elif question.category == "table":
        rewritten = f"Where does {ticker} report figures about {snippet}?"
    elif question.category == "filters":
        rewritten = f"In {section}, what does {ticker} say about {snippet}?"
    else:
        rewritten = f"What does {ticker} disclose about {snippet}?"
    payload = question.model_dump(mode="json")
    payload["question"] = rewritten
    digest = hashlib.sha256(
        f"{question.split}|{question.category}|{rewritten}|{reference.accession_number}".encode()
    ).hexdigest()[:12]
    payload["question_id"] = f"{question.split}-{digest}"
    metadata = dict(payload.get("metadata") or {})
    metadata["review_method"] = "corpus_grounded_paraphrase"
    payload["metadata"] = metadata
    return EvalQuestion.model_validate(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refine template benchmark questions")
    parser.add_argument("--dataset", default="data/evals/retrieval_benchmark.jsonl")
    parser.add_argument("--output", default="data/evals/retrieval_benchmark.jsonl")
    args = parser.parse_args()

    questions = [_refine(question) for question in load_jsonl_dataset(args.dataset)]
    validate_reviewed_benchmark(questions)
    write_jsonl_dataset(args.output, questions)
    refined = sum(
        1
        for question in questions
        if question.metadata.get("review_method") == "corpus_grounded_paraphrase"
    )
    print({"output": args.output, "questions": len(questions), "refined": refined})


if __name__ == "__main__":
    main()
