"""Retrieval evaluation datasets, metrics, and runner."""

from fdre.evals.cross_sectional import (
    CrossSectionalMetrics,
    CrossSectionalOutcome,
    CrossSectionalQuestionMetrics,
    aggregate_cross_sectional_question_metrics,
    evaluate_cross_sectional_outcomes,
)
from fdre.evals.cross_sectional_reporting import (
    slice_cross_sectional_metrics_by_task,
    write_cross_sectional_eval_report,
)
from fdre.evals.cross_sectional_runner import (
    build_cross_sectional_screen_plan,
    run_cross_sectional_benchmark,
)
from fdre.evals.datasets import (
    EvalQuestion,
    EvidenceReference,
    compute_dataset_sha256,
    load_cross_sectional_benchmark,
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
    "CrossSectionalMetrics",
    "CrossSectionalOutcome",
    "CrossSectionalQuestionMetrics",
    "EvalQuestion",
    "EvaluationOutcome",
    "EvidenceReference",
    "VariantMetrics",
    "aggregate_cross_sectional_question_metrics",
    "build_cross_sectional_screen_plan",
    "compute_dataset_sha256",
    "evaluate_cross_sectional_outcomes",
    "evaluate_variants",
    "evaluate_variants_at_ks",
    "load_cross_sectional_benchmark",
    "load_jsonl_dataset",
    "run_cross_sectional_benchmark",
    "slice_cross_sectional_metrics_by_task",
    "validate_benchmark",
    "validate_reviewed_benchmark",
    "write_cross_sectional_eval_report",
    "write_eval_report",
    "write_jsonl_dataset",
    "write_multi_k_eval_report",
]
