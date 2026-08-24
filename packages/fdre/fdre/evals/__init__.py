"""Retrieval evaluation datasets, metrics, and runner."""

from fdre.evals.datasets import (
    EvalQuestion,
    EvidenceReference,
    compute_dataset_sha256,
    load_jsonl_dataset,
    validate_benchmark,
    validate_reviewed_benchmark,
    write_jsonl_dataset,
)
from fdre.evals.runner import (
    EvaluationOutcome,
    VariantMetrics,
    evaluate_variants,
    evaluate_variants_at_ks,
    write_eval_report,
    write_multi_k_eval_report,
)

__all__ = [
    "EvalQuestion",
    "EvaluationOutcome",
    "EvidenceReference",
    "VariantMetrics",
    "compute_dataset_sha256",
    "evaluate_variants",
    "evaluate_variants_at_ks",
    "load_jsonl_dataset",
    "validate_benchmark",
    "validate_reviewed_benchmark",
    "write_eval_report",
    "write_jsonl_dataset",
    "write_multi_k_eval_report",
]
