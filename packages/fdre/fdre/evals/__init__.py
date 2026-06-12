"""Retrieval evaluation datasets, metrics, and runner."""

from fdre.evals.datasets import (
    EvalQuestion,
    EvidenceReference,
    load_jsonl_dataset,
    validate_reviewed_benchmark,
    write_jsonl_dataset,
)
from fdre.evals.runner import (
    EvaluationOutcome,
    VariantMetrics,
    evaluate_variants,
    write_eval_report,
)

__all__ = [
    "EvalQuestion",
    "EvaluationOutcome",
    "EvidenceReference",
    "VariantMetrics",
    "evaluate_variants",
    "load_jsonl_dataset",
    "validate_reviewed_benchmark",
    "write_eval_report",
    "write_jsonl_dataset",
]
