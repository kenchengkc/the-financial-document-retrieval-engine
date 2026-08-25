from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fdre.evals.cross_sectional import (
    CrossSectionalMetrics,
    CrossSectionalQuestionMetrics,
    aggregate_cross_sectional_question_metrics,
)


def slice_cross_sectional_metrics_by_task(
    metrics: CrossSectionalMetrics,
) -> dict[str, CrossSectionalMetrics]:
    grouped: dict[str, list[CrossSectionalQuestionMetrics]] = {}
    for question in metrics.per_question:
        grouped.setdefault(question.task_type, []).append(question)
    return {
        task_type: aggregate_cross_sectional_question_metrics(
            grouped[task_type],
            ks=metrics.ks,
        )
        for task_type in sorted(grouped)
    }


def write_cross_sectional_eval_report(
    output_dir: str | Path,
    metrics: CrossSectionalMetrics,
    *,
    benchmark_metadata: dict[str, Any] | None = None,
) -> tuple[Path, Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "cross_sectional_eval.json"
    markdown_path = directory / "cross_sectional_eval.md"
    per_query_path = directory / "cross_sectional_per_query.jsonl"

    by_task = slice_cross_sectional_metrics_by_task(metrics)
    payload = {
        "metadata": benchmark_metadata or {},
        "overall": _metrics_summary(metrics),
        "by_task_type": {
            task_type: _metrics_summary(task_metrics)
            for task_type, task_metrics in by_task.items()
        },
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    per_query_path.write_text(
        "".join(
            json.dumps(asdict(question), sort_keys=True) + "\n"
            for question in metrics.per_question
        )
    )
    markdown_path.write_text(
        _markdown_report(metrics, by_task, benchmark_metadata or {})
    )
    return json_path, markdown_path, per_query_path


def _metrics_summary(metrics: CrossSectionalMetrics) -> dict[str, Any]:
    return {
        "question_count": metrics.question_count,
        "ks": list(metrics.ks),
        "issuer_recall_at_k": metrics.issuer_recall_at_k,
        "issuer_precision_at_k": metrics.issuer_precision_at_k,
        "evidence_recall_at_k": metrics.evidence_recall_at_k,
        "mean_max_issuer_evidence_share": metrics.mean_max_issuer_evidence_share,
        "pit_leakage_rate": metrics.pit_leakage_rate,
        "zero_result_accuracy": metrics.zero_result_accuracy,
        "latency_p50_ms": metrics.latency_p50_ms,
        "latency_p95_ms": metrics.latency_p95_ms,
        "mean_semantic_search_calls": metrics.mean_semantic_search_calls,
        "max_semantic_search_calls": metrics.max_semantic_search_calls,
    }


def _markdown_report(
    metrics: CrossSectionalMetrics,
    by_task: dict[str, CrossSectionalMetrics],
    metadata: dict[str, Any],
) -> str:
    lines = ["# FDRE Cross-Sectional Evaluation", ""]
    if metadata:
        lines.extend(["## Run Metadata", ""])
        lines.extend(
            f"- **{key}:** `{_metadata_value(value)}`"
            for key, value in sorted(metadata.items())
        )
        lines.append("")

    lines.extend(
        [
            "## Overall",
            "",
            f"Questions: **{metrics.question_count}**",
            "",
            _cutoff_table(metrics),
            "",
            f"- PIT leakage: **{metrics.pit_leakage_rate:.3%}**",
            f"- Zero-result accuracy: **{_optional_rate(metrics.zero_result_accuracy)}**",
            f"- Mean max-issuer evidence share: **{metrics.mean_max_issuer_evidence_share:.3f}**",
            f"- p50 latency: **{metrics.latency_p50_ms:.1f} ms**",
            f"- p95 latency: **{metrics.latency_p95_ms:.1f} ms**",
            f"- Mean semantic-search calls: **{metrics.mean_semantic_search_calls:.3f}**",
            f"- Max semantic-search calls: **{metrics.max_semantic_search_calls}**",
            "",
            "## By Task Type",
            "",
        ]
    )
    if not by_task:
        lines.append("No task slices available.")
        return "\n".join(lines) + "\n"

    recall_headers = " | ".join(f"Issuer R@{k}" for k in metrics.ks)
    precision_headers = " | ".join(f"Issuer P@{k}" for k in metrics.ks)
    evidence_headers = " | ".join(f"Evidence R@{k}" for k in metrics.ks)
    lines.extend(
        [
            f"| Task type | N | {recall_headers} | {precision_headers} | "
            f"{evidence_headers} | PIT leakage | Zero-result acc. | p95 ms | Mean semantic calls |",
            "| --- | ---: | "
            + " | ".join("---:" for _ in range(len(metrics.ks) * 3 + 4))
            + " |",
        ]
    )
    for task_type, task_metrics in by_task.items():
        recall_values = " | ".join(
            f"{task_metrics.issuer_recall_at_k[k]:.3f}" for k in metrics.ks
        )
        precision_values = " | ".join(
            f"{task_metrics.issuer_precision_at_k[k]:.3f}" for k in metrics.ks
        )
        evidence_values = " | ".join(
            f"{task_metrics.evidence_recall_at_k[k]:.3f}" for k in metrics.ks
        )
        lines.append(
            f"| {task_type} | {task_metrics.question_count} | {recall_values} | "
            f"{precision_values} | {evidence_values} | "
            f"{task_metrics.pit_leakage_rate:.3%} | "
            f"{_optional_rate(task_metrics.zero_result_accuracy)} | "
            f"{task_metrics.latency_p95_ms:.1f} | "
            f"{task_metrics.mean_semantic_search_calls:.3f} |"
        )
    return "\n".join(lines) + "\n"


def _cutoff_table(metrics: CrossSectionalMetrics) -> str:
    lines = [
        "| Metric | " + " | ".join(f"@{k}" for k in metrics.ks) + " |",
        "| --- | " + " | ".join("---:" for _ in metrics.ks) + " |",
        "| Issuer Recall | "
        + " | ".join(f"{metrics.issuer_recall_at_k[k]:.3f}" for k in metrics.ks)
        + " |",
        "| Issuer Precision | "
        + " | ".join(f"{metrics.issuer_precision_at_k[k]:.3f}" for k in metrics.ks)
        + " |",
        "| Evidence Recall | "
        + " | ".join(f"{metrics.evidence_recall_at_k[k]:.3f}" for k in metrics.ks)
        + " |",
    ]
    return "\n".join(lines)


def _metadata_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _optional_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3%}"
