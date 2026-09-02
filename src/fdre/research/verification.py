from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fdre.research.panel import (
    FeatureLineage,
    ResearchPanel,
    _feature_lineage_id,
    validate_point_in_time_rows,
)
from fdre.research.screen import (
    ResearchScreenResponse,
    _feature_lineage_digest,
    _latest_rows_by_ticker,
    _plan_hash,
    validate_screen_lineage,
)
from fdre.research.signal_study import SignalStudyReport


def verify_feature_lineage(
    lineage: FeatureLineage,
    *,
    as_of: datetime | None = None,
) -> None:
    """Verify one feature-lineage record without recomputing the feature value."""
    if set(lineage.source_accessions) != set(lineage.source_available_at):
        raise ValueError(f"Feature lineage sources incomplete: {lineage.feature}")
    expected_max = max(lineage.source_available_at.values())
    if lineage.max_source_available_at != expected_max:
        raise ValueError(f"Feature lineage availability mismatch: {lineage.feature}")
    if as_of is not None and lineage.max_source_available_at > as_of:
        raise ValueError(f"Point-in-time feature leakage: {lineage.feature}")
    expected_id = _feature_lineage_id(
        feature=lineage.feature,
        calculation_version=lineage.calculation_version,
        parameters=lineage.parameters,
        source_accessions=lineage.source_accessions,
        source_available_at=lineage.source_available_at,
        corpus_snapshot_id=lineage.corpus_snapshot_id,
    )
    if lineage.lineage_id != expected_id:
        raise ValueError(f"Feature lineage hash mismatch: {lineage.feature}")


def verify_research_panel_lineage(panel: ResearchPanel) -> None:
    """Verify panel-level PIT, snapshot, and feature-lineage consistency."""
    validate_point_in_time_rows(panel.rows)
    for row in panel.rows:
        if row.corpus_snapshot_id != panel.corpus_snapshot_id:
            raise ValueError(
                f"Panel row snapshot mismatch for {row.accession_number}"
            )
        if row.calculation_version != panel.feature_version:
            raise ValueError(
                f"Panel row feature version mismatch for {row.accession_number}"
            )
        for lineage in row.feature_lineage.values():
            verify_feature_lineage(lineage, as_of=row.available_at)
            if lineage.corpus_snapshot_id != panel.corpus_snapshot_id:
                raise ValueError(
                    f"Feature lineage snapshot mismatch for {row.accession_number}: "
                    f"{lineage.feature}"
                )


def verify_research_panel_export(path: str | Path) -> int:
    """Verify lineage embedded in a JSON/CSV/Parquet research-panel export.

    Returns the number of verified rows. The export format intentionally contains rows
    rather than the original query envelope, so this verifies row/feature integrity and
    snapshot consistency, not reconstruction of the query that produced the panel.
    """
    source = Path(path)
    suffix = source.suffix.casefold()
    if suffix == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Research panel JSON must be an array of row objects")
        records = payload
    elif suffix == ".csv":
        with source.open(newline="", encoding="utf-8") as input_file:
            records = list(csv.DictReader(input_file))
    elif suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as error:
            raise RuntimeError(
                "Parquet panel verification requires `pip install -e '.[data]'`."
            ) from error
        records = pq.read_table(source).to_pylist()  # type: ignore[no-untyped-call, unused-ignore]
    else:
        raise ValueError("Research panel verification supports .json, .csv, or .parquet")

    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Research panel export rows must be objects")
        _verify_panel_export_record(record)
    return len(records)


def verify_research_screen_lineage(
    response: ResearchScreenResponse,
    panel: ResearchPanel,
) -> None:
    """Replay deterministic screen lineage against the PIT panel used as input.

    Semantic-provider output is intentionally outside this digest. The verifier checks
    the plan, universe selection, structured feature inputs, returned-row lineage, and
    manifest identity against the supplied panel.
    """
    verify_research_panel_lineage(panel)
    plan = response.plan
    manifest = response.manifest
    plan_hash = _plan_hash(plan)
    if manifest.plan_hash != plan_hash:
        raise ValueError("Screen plan hash mismatch")
    if manifest.corpus_snapshot_id != panel.corpus_snapshot_id:
        raise ValueError("Screen corpus snapshot mismatch")
    if manifest.feature_version != panel.feature_version:
        raise ValueError("Screen feature version mismatch")

    latest_rows = _latest_rows_by_ticker(panel.rows)
    rows_by_accession = {row.accession_number: row for row in panel.rows}
    if manifest.universe_count != len(latest_rows):
        raise ValueError("Screen universe count mismatch")
    if manifest.matched_count != len(response.rows):
        raise ValueError("Screen matched count mismatch")

    expected_digest = _feature_lineage_digest(
        plan,
        plan_hash=plan_hash,
        corpus_snapshot_id=panel.corpus_snapshot_id,
        latest_rows=latest_rows,
        rows_by_accession=rows_by_accession,
    )
    if manifest.feature_lineage_digest != expected_digest:
        raise ValueError("Screen feature lineage digest mismatch")

    validate_screen_lineage(plan, response.rows)
    for result_row in response.rows:
        selected = latest_rows.get(result_row.ticker)
        if selected is None or selected.accession_number != result_row.accession_number:
            raise ValueError(f"Screen selected filing mismatch for {result_row.ticker}")
        if result_row.feature_lineage != selected.feature_lineage:
            raise ValueError(f"Screen current lineage mismatch for {result_row.ticker}")
        prior_accession = (
            selected.source_accessions[1] if len(selected.source_accessions) > 1 else None
        )
        prior = rows_by_accession.get(prior_accession) if prior_accession else None
        expected_prior_lineage = prior.feature_lineage if prior is not None else {}
        if result_row.prior_feature_lineage != expected_prior_lineage:
            raise ValueError(f"Screen prior lineage mismatch for {result_row.ticker}")


def verify_signal_study_lineage(report: SignalStudyReport) -> None:
    """Verify complete signal lineage and experiment identity from a saved report."""
    lineage_pairs = sorted(report.feature_lineage_by_accession.items())
    for accession, lineage_id in lineage_pairs:
        if len(lineage_id) != 64:
            raise ValueError(f"Invalid signal lineage ID for {accession}")
        try:
            int(lineage_id, 16)
        except ValueError as error:
            raise ValueError(f"Invalid signal lineage ID for {accession}") from error

    if not report.feature_lineage_complete:
        if report.feature_lineage_digest is not None:
            raise ValueError("Incomplete signal lineage must not claim a complete digest")
        return
    if not lineage_pairs:
        raise ValueError("Complete signal lineage requires at least one lineage record")

    expected_digest = hashlib.sha256(
        json.dumps(lineage_pairs, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if report.feature_lineage_digest != expected_digest:
        raise ValueError("Signal feature lineage digest mismatch")

    manifest: dict[str, object] = {
        "signal_name": report.signal_name,
        "outcome_name": report.outcome_name,
        "bootstrap_unit": report.bootstrap_unit,
        "n_quantiles": report.n_quantiles,
        "dataset_version": report.dataset_version,
        "feature_version": report.feature_version,
        "code_sha": report.code_sha,
        "neutralization": report.neutralization,
        "definition": report.definition,
        "config": report.config.model_dump(mode="json"),
        "events": sorted(report.feature_lineage_by_accession),
        "feature_lineage_by_accession": report.feature_lineage_by_accession,
        "feature_lineage_digest": report.feature_lineage_digest,
        "feature_lineage_complete": True,
    }
    expected_experiment_key = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if report.experiment_key != expected_experiment_key:
        raise ValueError("Signal experiment key mismatch")


def _verify_panel_export_record(record: dict[str, Any]) -> None:
    accession = str(record.get("accession_number") or "")
    if not accession:
        raise ValueError("Research panel export row is missing accession_number")
    available_at = _parse_datetime(record.get("available_at"), field="available_at")
    max_source_available_at = _parse_datetime(
        record.get("max_source_available_at"),
        field="max_source_available_at",
    )
    snapshot_id = str(record.get("corpus_snapshot_id") or "")
    if not snapshot_id:
        raise ValueError(f"Panel row snapshot missing for {accession}")

    source_accessions = _json_list(record.get("source_accessions"), field="source_accessions")
    raw_lineage = _json_object(record.get("feature_lineage"), field="feature_lineage")
    lineages: list[FeatureLineage] = []
    for feature, payload in raw_lineage.items():
        lineage = FeatureLineage.model_validate(payload)
        if lineage.feature != feature:
            raise ValueError(
                f"Feature lineage key mismatch for {accession}: {feature} != {lineage.feature}"
            )
        verify_feature_lineage(lineage, as_of=available_at)
        if lineage.corpus_snapshot_id != snapshot_id:
            raise ValueError(
                f"Feature lineage snapshot mismatch for {accession}: {feature}"
            )
        if any(source not in source_accessions for source in lineage.source_accessions):
            raise ValueError(
                f"Feature lineage references an unknown source for {accession}: {feature}"
            )
        lineages.append(lineage)

    expected_row_max = max(
        (lineage.max_source_available_at for lineage in lineages),
        default=available_at,
    )
    if max_source_available_at != expected_row_max:
        raise ValueError(f"Panel row information timestamp mismatch for {accession}")
    if max_source_available_at > available_at:
        raise ValueError(f"Point-in-time panel leakage for {accession}")


def _json_object(value: object, *, field: str) -> dict[str, Any]:
    parsed = _json_value(value, field=field)
    if not isinstance(parsed, dict):
        raise ValueError(f"{field} must decode to an object")
    return parsed


def _json_list(value: object, *, field: str) -> list[str]:
    parsed = _json_value(value, field=field)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ValueError(f"{field} must decode to a string array")
    return parsed


def _json_value(value: object, *, field: str) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"{field} must contain valid JSON") from error
    if value is None:
        raise ValueError(f"{field} is required")
    return value


def _parse_datetime(value: object, *, field: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{field} must be an ISO-8601 datetime") from error
    raise ValueError(f"{field} must be an ISO-8601 datetime")
