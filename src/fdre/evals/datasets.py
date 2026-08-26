from __future__ import annotations

import hashlib
import json
import math
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


def evidence_reference_matches(
    reference: EvidenceReference,
    *,
    accession_number: str,
    section: str | None,
    text: str,
) -> bool:
    """Match reviewed excerpt evidence against a returned filing passage."""
    reference_section = normalize_evidence_text(reference.section or "")
    candidate_section = normalize_evidence_text(section or "")
    section_ok = (
        not reference_section
        or not candidate_section
        or candidate_section == reference_section
    )
    return (
        accession_number == reference.accession_number
        and section_ok
        and reference.normalized_quote in normalize_evidence_text(text)
    )


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
        has_structured_gold = bool(_reviewed_conditions(question))
        if not question.should_abstain and not (
            question.relevant_evidence
            or question.relevant_chunk_ids
            or has_structured_gold
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


def validate_cross_sectional_evidence_grounding(
    questions: list[EvalQuestion],
) -> None:
    """Require semantic screen evidence to come from the selected gold filing."""
    errors: list[str] = []
    for question in questions:
        screen_plan = question.metadata.get("screen_plan")
        semantic_query = (
            screen_plan.get("semantic_query") if isinstance(screen_plan, dict) else None
        )
        if not question.relevant_evidence:
            if isinstance(semantic_query, str) and semantic_query:
                errors.append(
                    f"{question.question_id}: semantic screen has no reviewed evidence"
                )
            continue
        if len(question.expected_tickers) != 1:
            errors.append(f"{question.question_id}: expected exactly one gold ticker")
            continue
        expected_ticker = question.expected_tickers[0]
        selected_accession = question.metadata.get("selected_accession")
        if not isinstance(selected_accession, str) or not selected_accession:
            errors.append(f"{question.question_id}: missing metadata.selected_accession")
            continue
        for reference in question.relevant_evidence:
            if reference.accession_number != selected_accession:
                errors.append(
                    f"{question.question_id}: evidence accession "
                    f"{reference.accession_number} != selected {selected_accession}"
                )
            if reference.ticker != expected_ticker:
                errors.append(
                    f"{question.question_id}: evidence ticker "
                    f"{reference.ticker!r} != expected {expected_ticker}"
                )
    if errors:
        raise ValueError(
            "Invalid cross-sectional evidence grounding:\n- " + "\n- ".join(errors)
        )


def validate_cross_sectional_condition_grounding(
    questions: list[EvalQuestion],
) -> None:
    """Require every structured screen condition to carry reviewed PIT gold."""
    errors: list[str] = []
    for question in questions:
        expected_conditions = _reviewed_conditions(question)
        if not expected_conditions:
            continue
        if len(question.expected_tickers) != 1:
            errors.append(f"{question.question_id}: expected exactly one gold ticker")
            continue

        selected_accession = question.metadata.get("selected_accession")
        if not isinstance(selected_accession, str) or not selected_accession:
            errors.append(f"{question.question_id}: missing metadata.selected_accession")
        if "selected_prior_accession" not in question.metadata:
            errors.append(
                f"{question.question_id}: missing metadata.selected_prior_accession"
            )

        screen_plan = question.metadata.get("screen_plan")
        if not isinstance(screen_plan, dict):
            errors.append(f"{question.question_id}: missing metadata.screen_plan")
            continue
        plan_conditions = screen_plan.get("conditions")
        if not isinstance(plan_conditions, list) or not plan_conditions:
            errors.append(f"{question.question_id}: screen plan has no conditions")
            continue
        if len(plan_conditions) != len(expected_conditions):
            errors.append(
                f"{question.question_id}: expected_conditions count does not match "
                "screen_plan.conditions"
            )

        for index, expected in enumerate(expected_conditions):
            prefix = f"{question.question_id}: expected_conditions[{index}]"
            required_keys = {
                "metric",
                "feature",
                "operator",
                "threshold",
                "change_from_prior",
                "passed",
                "current_value",
                "prior_value",
                "observed_value",
                "current_lineage_id",
                "prior_lineage_id",
                "source_accessions",
            }
            missing = required_keys - expected.keys()
            if missing:
                errors.append(f"{prefix}: missing {', '.join(sorted(missing))}")
                continue
            if not _is_number(expected["threshold"]):
                errors.append(f"{prefix}: threshold must be numeric")
            if not isinstance(expected["change_from_prior"], bool):
                errors.append(f"{prefix}: change_from_prior must be boolean")
            if not isinstance(expected["passed"], bool):
                errors.append(f"{prefix}: passed must be boolean")
            if not _is_number(expected["current_value"]):
                errors.append(f"{prefix}: current_value must be numeric")
            if not _is_number(expected["observed_value"]):
                errors.append(f"{prefix}: observed_value must be numeric")
            if not _valid_lineage_id(expected["current_lineage_id"]):
                errors.append(f"{prefix}: invalid current_lineage_id")
            sources = expected["source_accessions"]
            if not (
                isinstance(sources, list)
                and sources
                and all(isinstance(value, str) and value for value in sources)
            ):
                errors.append(f"{prefix}: invalid source_accessions")

            if expected["change_from_prior"]:
                prior_accession = question.metadata.get("selected_prior_accession")
                if not isinstance(prior_accession, str) or not prior_accession:
                    errors.append(
                        f"{prefix}: change condition requires selected prior accession"
                    )
                if not _is_number(expected["prior_value"]):
                    errors.append(f"{prefix}: prior_value must be numeric for change")
                if not _valid_lineage_id(expected["prior_lineage_id"]):
                    errors.append(f"{prefix}: invalid prior_lineage_id for change")
            elif expected["prior_value"] is not None or expected["prior_lineage_id"] is not None:
                errors.append(
                    f"{prefix}: current-value condition must not pin prior value/lineage"
                )

            matching_plan_conditions = [
                condition
                for condition in plan_conditions
                if isinstance(condition, dict)
                and condition.get("metric") == expected["metric"]
                and condition.get("operator") == expected["operator"]
                and bool(condition.get("change_from_prior", False))
                == expected["change_from_prior"]
                and _numbers_match(condition.get("value"), expected["threshold"])
            ]
            if len(matching_plan_conditions) != 1:
                errors.append(
                    f"{prefix}: no unique matching condition in screen_plan.conditions"
                )
    if errors:
        raise ValueError(
            "Invalid cross-sectional condition grounding:\n- " + "\n- ".join(errors)
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
    source_dataset_path: str | Path | None = None,
) -> list[EvalQuestion]:
    """Load reviewed cross-sectional cases, with legacy evidence hydration fallback.

    Cross-sectional cases may carry direct filing evidence, reviewed structured-condition
    gold, or both. Older v1 cases without direct grounding can still hydrate evidence
    from the canonical retrieval benchmark. ``source_question_ids`` is provenance only
    when present on directly grounded cases.
    """
    questions = load_jsonl_dataset(path)
    source_by_id: dict[str, EvalQuestion] = {}
    if source_dataset_path is not None:
        source_by_id = {
            question.question_id: question
            for question in load_jsonl_dataset(source_dataset_path)
            if question.question_id is not None
        }

    hydrated: list[EvalQuestion] = []
    for question in questions:
        source_ids = question.metadata.get("source_question_ids")
        has_direct_grounding = bool(question.relevant_evidence) or bool(
            _reviewed_conditions(question)
        )
        if not isinstance(source_ids, list) or not source_ids:
            if has_direct_grounding:
                hydrated.append(question)
                continue
            raise ValueError(f"{question.question_id}: missing source_question_ids")

        if source_by_id:
            for source_id in source_ids:
                if not isinstance(source_id, str) or source_id not in source_by_id:
                    raise ValueError(
                        f"{question.question_id}: unknown source question {source_id!r}"
                    )
        if has_direct_grounding:
            hydrated.append(question)
            continue
        if not source_by_id:
            raise ValueError(
                f"{question.question_id}: no direct grounding and no source dataset"
            )
        evidence: list[EvidenceReference] = []
        for source_id in source_ids:
            if not isinstance(source_id, str):
                raise ValueError(
                    f"{question.question_id}: invalid source question {source_id!r}"
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


def _reviewed_conditions(question: EvalQuestion) -> list[dict[str, Any]]:
    payload = question.metadata.get("expected_conditions")
    if not isinstance(payload, list):
        return []
    return [record for record in payload if isinstance(record, dict)]


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _valid_lineage_id(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64


def _numbers_match(left: Any, right: Any) -> bool:
    return (
        _is_number(left)
        and _is_number(right)
        and math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-12)
    )


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates
