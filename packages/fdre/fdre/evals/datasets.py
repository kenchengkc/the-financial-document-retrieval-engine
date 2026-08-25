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

    # v2 fields — optional for backward compatibility with existing benchmarks.
    task_type: str | None = None
    """Precise retrieval/research operation (e.g. ``latest_filing``,
    ``comparison``, ``hard_negative``).  Falls back to *category* via
    :pyattr:`resolved_task_type` when absent."""

    as_of: str | None = None
    """ISO-8601 date or datetime indicating the point-in-time boundary.
    Evidence must be available at or before this timestamp."""

    @model_validator(mode="after")
    def assign_question_id(self) -> EvalQuestion:
        if self.question_id is None:
            digest = hashlib.sha256(self.question.encode("utf-8")).hexdigest()[:12]
            self.question_id = f"{self.split}-{digest}"
        return self

    @property
    def resolved_task_type(self) -> str:
        """Return *task_type* when set, otherwise fall back to *category*."""
        return self.task_type or self.category


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


def compute_dataset_sha256(questions: list[EvalQuestion]) -> str:
    """Deterministic SHA-256 of canonical benchmark content.

    Serializes each question to sorted-key JSON, joins with newlines, and
    hashes. The result is stable across re-serialization as long as the
    Pydantic model fields and values remain identical.
    """
    canonical = "\n".join(
        json.dumps(question.model_dump(mode="json"), sort_keys=True)
        for question in questions
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_benchmark(
    questions: list[EvalQuestion],
    *,
    expected_count: int | None = None,
    expected_splits: dict[str, int] | None = None,
    required_categories: set[str] | None = None,
) -> None:
    """Flexible benchmark validation for v2+ datasets.

    All constraints are optional.  Pass only the invariants that apply to
    the dataset under test.
    """
    errors: list[str] = []
    if expected_count is not None and len(questions) != expected_count:
        errors.append(f"expected {expected_count} questions, found {len(questions)}")
    if expected_splits is not None:
        split_counts: dict[str, int] = {}
        for question in questions:
            split_counts[question.split] = split_counts.get(question.split, 0) + 1
        for split_name, expected in expected_splits.items():
            actual = split_counts.get(split_name, 0)
            if actual != expected:
                errors.append(
                    f"expected {expected} {split_name} questions, found {actual}"
                )
    if required_categories is not None:
        categories = {question.category for question in questions}
        missing_categories = required_categories - categories
        if missing_categories:
            errors.append(
                f"missing categories: {', '.join(sorted(missing_categories))}"
            )
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
        raise ValueError("Invalid benchmark:\n- " + "\n- ".join(errors))


def validate_reviewed_benchmark(questions: list[EvalQuestion]) -> None:
    """Validate the immutable v1 reviewed benchmark contract (120 / 80 / 40)."""
    validate_benchmark(
        questions,
        expected_count=120,
        expected_splits={"development": 80, "holdout": 40},
        required_categories=REQUIRED_BENCHMARK_CATEGORIES,
    )


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


def load_cross_sectional_benchmark(
    path: str | Path,
    *,
    source_dataset_path: str | Path,
) -> list[EvalQuestion]:
    """Hydrate cross-sectional cases with canonical reviewed evidence."""
    questions = load_jsonl_dataset(path)
    source_questions = load_jsonl_dataset(source_dataset_path)
    source_by_id = {
        question.question_id: question
        for question in source_questions
        if question.question_id is not None
    }

    hydrated: list[EvalQuestion] = []
    for question in questions:
        source_ids = question.metadata.get("source_question_ids")
        if not isinstance(source_ids, list) or not source_ids:
            raise ValueError(f"{question.question_id}: missing source_question_ids")
        evidence: list[EvidenceReference] = []
        for source_id in source_ids:
            if not isinstance(source_id, str) or source_id not in source_by_id:
                raise ValueError(
                    f"{question.question_id}: unknown source question {source_id!r}"
                )
            evidence.extend(source_by_id[source_id].relevant_evidence)
        hydrated.append(question.model_copy(update={"relevant_evidence": evidence}))
    return hydrated


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
