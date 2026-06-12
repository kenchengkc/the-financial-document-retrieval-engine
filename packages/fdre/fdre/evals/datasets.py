from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

BenchmarkSplit = Literal["development", "holdout"]


def normalize_evidence_text(value: str) -> str:
    return " ".join(re.sub(r"\s+", " ", value).strip().casefold().split())


def evidence_fingerprint(value: str) -> str:
    return hashlib.sha256(normalize_evidence_text(value).encode("utf-8")).hexdigest()


class EvidenceReference(BaseModel):
    accession_number: str
    section: str | None = None
    normalized_quote: str = Field(min_length=1)
    content_fingerprint: str = Field(min_length=64, max_length=64)
    ticker: str | None = None

    @classmethod
    def from_quote(
        cls,
        *,
        accession_number: str,
        quote: str,
        section: str | None = None,
        ticker: str | None = None,
    ) -> EvidenceReference:
        normalized_quote = normalize_evidence_text(quote)
        return cls(
            accession_number=accession_number,
            section=section,
            normalized_quote=normalized_quote,
            content_fingerprint=evidence_fingerprint(normalized_quote),
            ticker=ticker,
        )

    @model_validator(mode="after")
    def validate_fingerprint(self) -> EvidenceReference:
        if evidence_fingerprint(self.normalized_quote) != self.content_fingerprint:
            raise ValueError("content_fingerprint does not match normalized_quote")
        self.normalized_quote = normalize_evidence_text(self.normalized_quote)
        return self


class EvalQuestion(BaseModel):
    question_id: str | None = None
    question: str
    split: BenchmarkSplit = "development"
    category: str = "narrative"
    expected_tickers: list[str] = Field(default_factory=list)
    expected_sections: list[str] = Field(default_factory=list)
    relevant_evidence: list[EvidenceReference] = Field(default_factory=list)
    relevant_chunk_ids: list[int] = Field(default_factory=list)
    answer_type: str = "text"
    should_abstain: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def assign_question_id(self) -> EvalQuestion:
        if self.question_id is None:
            digest = hashlib.sha256(self.question.encode("utf-8")).hexdigest()[:12]
            self.question_id = f"{self.split}-{digest}"
        return self


REQUIRED_BENCHMARK_CATEGORIES = {
    "narrative",
    "table",
    "legal",
    "guidance",
    "temporal",
    "cross_sectional",
    "filters",
    "abstention",
}


def validate_reviewed_benchmark(questions: list[EvalQuestion]) -> None:
    errors: list[str] = []
    if len(questions) != 120:
        errors.append(f"expected 120 questions, found {len(questions)}")
    development = sum(question.split == "development" for question in questions)
    holdout = sum(question.split == "holdout" for question in questions)
    if development != 80 or holdout != 40:
        errors.append(f"expected 80/40 development/holdout split, found {development}/{holdout}")
    categories = {question.category for question in questions}
    missing_categories = REQUIRED_BENCHMARK_CATEGORIES - categories
    if missing_categories:
        errors.append(f"missing categories: {', '.join(sorted(missing_categories))}")
    duplicate_ids = _duplicates(
        question.question_id for question in questions if question.question_id is not None
    )
    if duplicate_ids:
        errors.append(f"duplicate question IDs: {', '.join(sorted(duplicate_ids))}")
    for question in questions:
        if not question.should_abstain and not (
            question.relevant_evidence or question.relevant_chunk_ids
        ):
            errors.append(f"{question.question_id}: no relevant evidence")
        if not question.metadata.get("reviewed_by"):
            errors.append(f"{question.question_id}: missing metadata.reviewed_by")
    if errors:
        raise ValueError("Invalid reviewed benchmark:\n- " + "\n- ".join(errors))


def load_jsonl_dataset(path: str | Path) -> list[EvalQuestion]:
    questions: list[EvalQuestion] = []
    for line_number, line in enumerate(Path(path).read_text().splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            questions.append(EvalQuestion.model_validate_json(stripped))
        except ValueError as error:
            raise ValueError(f"Invalid eval record on line {line_number}") from error
    return questions


def write_jsonl_dataset(path: str | Path, questions: list[EvalQuestion]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(
            json.dumps(question.model_dump(mode="json"), sort_keys=True)
            for question in questions
        )
        + "\n"
    )


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates
