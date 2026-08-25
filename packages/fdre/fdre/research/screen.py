from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import Chunk, Company, Document
from fdre.research.panel import (
    FEATURE_VERSION,
    FeatureLineage,
    PanelFeature,
    ResearchPanelQuery,
    ResearchPanelRow,
    build_research_panel,
)
from fdre.retrieval.query import RetrievalCandidate, SearchFilters

ScreenMetric = Literal[
    "revenue_growth",
    "operating_margin",
    "net_margin",
    "capex_to_revenue",
    "operating_cash_flow_to_revenue",
    "risk_churn_rate",
    "filing_delay_days",
]
ComparisonOperator = Literal["gt", "gte", "lt", "lte"]
ScreenRankField = Literal[
    "semantic_score",
    "revenue_growth",
    "operating_margin",
    "net_margin",
    "capex_to_revenue",
    "operating_cash_flow_to_revenue",
    "risk_churn_rate",
    "filing_delay_days",
]
SemanticSearch = Callable[[str, SearchFilters, int], list[RetrievalCandidate]]

_SCREEN_METRIC_FEATURE: dict[ScreenMetric, PanelFeature] = {
    "revenue_growth": "xbrl_growth",
    "operating_margin": "xbrl_margins",
    "net_margin": "xbrl_margins",
    "capex_to_revenue": "xbrl_margins",
    "operating_cash_flow_to_revenue": "xbrl_margins",
    "risk_churn_rate": "risk_changes",
    "filing_delay_days": "filing_timing",
}


class ScreenCondition(BaseModel):
    metric: ScreenMetric
    operator: ComparisonOperator
    value: float
    change_from_prior: bool = False


class ResearchScreenPlan(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    as_of: datetime
    form_types: list[str] = Field(default_factory=lambda: ["10-Q"])
    sections: list[str] = Field(default_factory=list)
    conditions: list[ScreenCondition] = Field(default_factory=list)
    semantic_query: str | None = Field(default=None, min_length=1)
    semantic_min_score: float | None = None
    semantic_candidate_limit: int = Field(default=50, ge=1, le=100)
    evidence_per_issuer: int = Field(default=2, ge=1, le=5)
    rank_by: ScreenRankField = "semantic_score"
    descending: bool = True
    limit: int = Field(default=25, ge=1, le=100)

    @field_validator("as_of")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must include a UTC offset")
        return value

    @model_validator(mode="after")
    def validate_rank_source(self) -> ResearchScreenPlan:
        if self.rank_by == "semantic_score" and self.semantic_query is None:
            raise ValueError("semantic_score ranking requires semantic_query")
        return self


class ScreenConditionResult(BaseModel):
    metric: ScreenMetric
    feature: PanelFeature
    operator: ComparisonOperator
    threshold: float
    change_from_prior: bool
    current_value: float | None
    prior_value: float | None
    observed_value: float | None
    passed: bool
    current_lineage_id: str = Field(min_length=64, max_length=64)
    prior_lineage_id: str | None = Field(default=None, min_length=64, max_length=64)
    source_accessions: list[str]
    max_information_timestamp: datetime


class ResearchScreenRow(BaseModel):
    ticker: str
    accession_number: str
    prior_accession_number: str | None
    form_type: str
    period_end: date | None
    available_at: datetime
    semantic_score: float | None
    rank_value: float | None
    conditions: list[ScreenConditionResult]
    evidence: list[RetrievalCandidate]
    source_accessions: list[str]
    feature_provenance: dict[str, list[str]]
    feature_lineage: dict[PanelFeature, FeatureLineage] = Field(default_factory=dict)
    prior_feature_lineage: dict[PanelFeature, FeatureLineage] = Field(default_factory=dict)
    max_source_available_at: datetime


class ResearchScreenManifest(BaseModel):
    plan_hash: str
    feature_lineage_digest: str = Field(min_length=64, max_length=64)
    corpus_snapshot_id: str
    feature_version: str
    universe_count: int
    structured_match_count: int
    semantic_search_calls: int
    semantic_candidate_count: int
    matched_count: int
    max_information_timestamp: datetime | None


class ResearchScreenResponse(BaseModel):
    plan: ResearchScreenPlan
    manifest: ResearchScreenManifest
    rows: list[ResearchScreenRow]
    latency_ms: int = 0


def execute_research_screen(
    session: Session,
    plan: ResearchScreenPlan,
    *,
    semantic_search: SemanticSearch | None = None,
) -> ResearchScreenResponse:
    """Execute a bounded point-in-time cross-sectional research screen.

    Structured conditions are evaluated before optional semantic retrieval. A semantic
    screen invokes the supplied search function at most once, and returned evidence is
    restricted to the exact latest filing selected for each issuer.
    """
    panel = build_research_panel(
        session,
        ResearchPanelQuery(
            tickers=plan.tickers,
            as_of=plan.as_of,
            form_types=plan.form_types,
            sections=plan.sections,
            include_amendments=False,
            limit=10_000,
        ),
    )
    latest_rows = _latest_rows_by_ticker(panel.rows)
    rows_by_accession = {row.accession_number: row for row in panel.rows}

    structured_matches: list[tuple[ResearchPanelRow, list[ScreenConditionResult]]] = []
    for row in latest_rows.values():
        condition_results = [
            _evaluate_condition(
                row,
                rows_by_accession,
                condition,
                as_of=plan.as_of,
            )
            for condition in plan.conditions
        ]
        if all(result.passed for result in condition_results):
            structured_matches.append((row, condition_results))

    evidence_by_ticker: dict[str, list[RetrievalCandidate]] = {}
    semantic_candidate_count = 0
    semantic_search_calls = 0
    if plan.semantic_query is not None and structured_matches:
        if semantic_search is None:
            raise ValueError("semantic_search is required when semantic_query is set")
        survivor_rows = [row for row, _ in structured_matches]
        filters = SearchFilters(
            tickers=(
                [row.ticker for row in survivor_rows]
                if plan.conditions or plan.tickers
                else []
            ),
            form_types=[form.upper() for form in plan.form_types],
            accepted_at_from=_aware_datetime(
                min(row.available_at for row in survivor_rows),
                reference=plan.as_of,
            ),
            accepted_at_to=plan.as_of,
            as_of=plan.as_of,
            amendment_policy="exclude",
            sections=plan.sections,
        )
        candidates = semantic_search(
            plan.semantic_query,
            filters,
            plan.semantic_candidate_limit,
        )
        semantic_search_calls = 1
        semantic_candidate_count = len(candidates)
        evidence_by_ticker = _latest_filing_evidence(
            session,
            candidates,
            latest_rows={row.ticker: row for row in survivor_rows},
            evidence_per_issuer=plan.evidence_per_issuer,
        )

    rows: list[ResearchScreenRow] = []
    for row, condition_results in structured_matches:
        evidence = evidence_by_ticker.get(row.ticker, [])
        semantic_score = _candidate_score(evidence[0]) if evidence else None
        if plan.semantic_query is not None:
            if semantic_score is None:
                continue
            if (
                plan.semantic_min_score is not None
                and semantic_score < plan.semantic_min_score
            ):
                continue
        rank_value = (
            semantic_score
            if plan.rank_by == "semantic_score"
            else _metric_value(row, plan.rank_by)
        )
        prior_row = _prior_row(row, rows_by_accession)
        rows.append(
            ResearchScreenRow(
                ticker=row.ticker,
                accession_number=row.accession_number,
                prior_accession_number=(
                    prior_row.accession_number if prior_row is not None else None
                ),
                form_type=row.form_type,
                period_end=row.period_end,
                available_at=row.available_at,
                semantic_score=semantic_score,
                rank_value=rank_value,
                conditions=condition_results,
                evidence=evidence,
                source_accessions=row.source_accessions,
                feature_provenance=row.feature_provenance,
                feature_lineage=row.feature_lineage,
                prior_feature_lineage=(
                    prior_row.feature_lineage if prior_row is not None else {}
                ),
                max_source_available_at=row.max_source_available_at,
            )
        )

    rows.sort(key=lambda item: _rank_key(item, descending=plan.descending))
    rows = rows[: plan.limit]
    validate_screen_lineage(plan, rows)

    max_information_timestamp = max(
        (
            _aware_datetime(row.max_source_available_at, reference=plan.as_of)
            for row in latest_rows.values()
        ),
        default=None,
    )
    if max_information_timestamp is not None and max_information_timestamp > plan.as_of:
        raise ValueError("point-in-time screen included information after as_of")

    plan_hash = _plan_hash(plan)
    return ResearchScreenResponse(
        plan=plan,
        manifest=ResearchScreenManifest(
            plan_hash=plan_hash,
            feature_lineage_digest=_feature_lineage_digest(
                plan,
                plan_hash=plan_hash,
                corpus_snapshot_id=panel.corpus_snapshot_id,
                latest_rows=latest_rows,
                rows_by_accession=rows_by_accession,
            ),
            corpus_snapshot_id=panel.corpus_snapshot_id,
            feature_version=FEATURE_VERSION,
            universe_count=len(latest_rows),
            structured_match_count=len(structured_matches),
            semantic_search_calls=semantic_search_calls,
            semantic_candidate_count=semantic_candidate_count,
            matched_count=len(rows),
            max_information_timestamp=max_information_timestamp,
        ),
        rows=rows,
    )


def validate_screen_lineage(
    plan: ResearchScreenPlan,
    rows: list[ResearchScreenRow],
) -> None:
    for row in rows:
        for lineage in [
            *row.feature_lineage.values(),
            *row.prior_feature_lineage.values(),
        ]:
            lineage_time = _aware_datetime(
                lineage.max_source_available_at,
                reference=plan.as_of,
            )
            if lineage_time > plan.as_of:
                raise ValueError(
                    f"point-in-time screen lineage included information after as_of: "
                    f"{row.ticker} {lineage.feature}"
                )

        for condition in row.conditions:
            current_lineage = row.feature_lineage.get(condition.feature)
            if (
                current_lineage is None
                or current_lineage.lineage_id != condition.current_lineage_id
            ):
                raise ValueError(
                    f"screen condition lineage mismatch for {row.ticker}: "
                    f"{condition.metric}"
                )

            prior_lineage = row.prior_feature_lineage.get(condition.feature)
            if condition.prior_lineage_id is None:
                if condition.change_from_prior and prior_lineage is not None:
                    raise ValueError(
                        f"screen condition prior lineage missing for {row.ticker}: "
                        f"{condition.metric}"
                    )
            elif (
                prior_lineage is None
                or prior_lineage.lineage_id != condition.prior_lineage_id
            ):
                raise ValueError(
                    f"screen condition prior lineage mismatch for {row.ticker}: "
                    f"{condition.metric}"
                )

            expected_sources = _combined_source_accessions(
                current_lineage,
                prior_lineage if condition.prior_lineage_id is not None else None,
            )
            if condition.source_accessions != expected_sources:
                raise ValueError(
                    f"screen condition sources mismatch for {row.ticker}: "
                    f"{condition.metric}"
                )

            lineage_times = [
                _aware_datetime(
                    current_lineage.max_source_available_at,
                    reference=plan.as_of,
                )
            ]
            if condition.prior_lineage_id is not None and prior_lineage is not None:
                lineage_times.append(
                    _aware_datetime(
                        prior_lineage.max_source_available_at,
                        reference=plan.as_of,
                    )
                )
            expected_max = max(lineage_times)
            observed_max = _aware_datetime(
                condition.max_information_timestamp,
                reference=plan.as_of,
            )
            if observed_max != expected_max:
                raise ValueError(
                    f"screen condition information timestamp mismatch for "
                    f"{row.ticker}: {condition.metric}"
                )
            if observed_max > plan.as_of:
                raise ValueError(
                    f"point-in-time condition lineage included information after as_of: "
                    f"{row.ticker} {condition.metric}"
                )


def _latest_rows_by_ticker(
    rows: list[ResearchPanelRow],
) -> dict[str, ResearchPanelRow]:
    latest: dict[str, ResearchPanelRow] = {}
    for row in rows:
        incumbent = latest.get(row.ticker)
        if incumbent is None or _filing_sort_key(row) > _filing_sort_key(incumbent):
            latest[row.ticker] = row
    return latest


def _filing_sort_key(row: ResearchPanelRow) -> tuple[date, datetime, str]:
    return (row.period_end or date.min, row.available_at, row.accession_number)


def _evaluate_condition(
    row: ResearchPanelRow,
    rows_by_accession: dict[str, ResearchPanelRow],
    condition: ScreenCondition,
    *,
    as_of: datetime,
) -> ScreenConditionResult:
    feature = _SCREEN_METRIC_FEATURE[condition.metric]
    current_lineage = _required_feature_lineage(row, feature)
    current_value = _metric_value(row, condition.metric)
    prior_row = _prior_row(row, rows_by_accession)
    prior_value: float | None = None
    prior_lineage: FeatureLineage | None = None
    observed_value = current_value
    if condition.change_from_prior:
        if prior_row is not None:
            prior_value = _metric_value(prior_row, condition.metric)
            prior_lineage = _required_feature_lineage(prior_row, feature)
        observed_value = (
            current_value - prior_value
            if current_value is not None and prior_value is not None
            else None
        )

    lineage_times = [
        _aware_datetime(
            current_lineage.max_source_available_at,
            reference=as_of,
        )
    ]
    if prior_lineage is not None:
        lineage_times.append(
            _aware_datetime(
                prior_lineage.max_source_available_at,
                reference=as_of,
            )
        )
    max_information_timestamp = max(lineage_times)
    if max_information_timestamp > as_of:
        raise ValueError(
            f"point-in-time condition lineage included information after as_of: "
            f"{row.ticker} {condition.metric}"
        )

    return ScreenConditionResult(
        metric=condition.metric,
        feature=feature,
        operator=condition.operator,
        threshold=condition.value,
        change_from_prior=condition.change_from_prior,
        current_value=current_value,
        prior_value=prior_value,
        observed_value=observed_value,
        passed=(
            observed_value is not None
            and _compare(observed_value, condition.operator, condition.value)
        ),
        current_lineage_id=current_lineage.lineage_id,
        prior_lineage_id=(prior_lineage.lineage_id if prior_lineage is not None else None),
        source_accessions=_combined_source_accessions(
            current_lineage,
            prior_lineage,
        ),
        max_information_timestamp=max_information_timestamp,
    )


def _required_feature_lineage(
    row: ResearchPanelRow,
    feature: PanelFeature,
) -> FeatureLineage:
    lineage = row.feature_lineage.get(feature)
    if lineage is None:
        raise ValueError(
            f"screen metric requires missing feature lineage: {row.ticker} {feature}"
        )
    return lineage


def _prior_row(
    row: ResearchPanelRow,
    rows_by_accession: dict[str, ResearchPanelRow],
) -> ResearchPanelRow | None:
    prior_accession = row.source_accessions[1] if len(row.source_accessions) > 1 else None
    return rows_by_accession.get(prior_accession) if prior_accession else None


def _combined_source_accessions(
    current_lineage: FeatureLineage,
    prior_lineage: FeatureLineage | None,
) -> list[str]:
    combined: list[str] = []
    for accession in [
        *current_lineage.source_accessions,
        *(prior_lineage.source_accessions if prior_lineage is not None else []),
    ]:
        if accession not in combined:
            combined.append(accession)
    return combined


def _metric_value(row: ResearchPanelRow, metric: ScreenMetric) -> float | None:
    value = getattr(row, metric)
    return float(value) if value is not None else None


def _compare(value: float, operator: ComparisonOperator, threshold: float) -> bool:
    if operator == "gt":
        return value > threshold
    if operator == "gte":
        return value >= threshold
    if operator == "lt":
        return value < threshold
    return value <= threshold


def _latest_filing_evidence(
    session: Session,
    candidates: list[RetrievalCandidate],
    *,
    latest_rows: dict[str, ResearchPanelRow],
    evidence_per_issuer: int,
) -> dict[str, list[RetrievalCandidate]]:
    if not candidates:
        return {}
    chunk_ids = [candidate.chunk_id for candidate in candidates]
    chunk_documents = {
        int(chunk_id): (ticker, accession_number)
        for chunk_id, ticker, accession_number in session.execute(
            select(Chunk.id, Company.ticker, Document.accession_number)
            .join(Document, Document.id == Chunk.document_id)
            .join(Company, Company.id == Document.company_id)
            .where(Chunk.id.in_(chunk_ids))
        )
    }
    grouped: dict[str, list[RetrievalCandidate]] = {}
    for candidate in candidates:
        identity = chunk_documents.get(candidate.chunk_id)
        if identity is None:
            continue
        ticker, accession_number = identity
        selected = latest_rows.get(ticker)
        if selected is None or selected.accession_number != accession_number:
            continue
        evidence = grouped.setdefault(ticker, [])
        if len(evidence) < evidence_per_issuer:
            evidence.append(candidate)
    return grouped


def _candidate_score(candidate: RetrievalCandidate) -> float:
    for score in (
        candidate.rerank_score,
        candidate.hybrid_score,
        candidate.dense_score,
        candidate.sparse_score,
    ):
        if score is not None:
            return float(score)
    return 0.0


def _rank_key(
    row: ResearchScreenRow,
    *,
    descending: bool,
) -> tuple[bool, float, str]:
    missing = row.rank_value is None
    value = row.rank_value or 0.0
    return (missing, -value if descending else value, row.ticker)


def _feature_lineage_digest(
    plan: ResearchScreenPlan,
    *,
    plan_hash: str,
    corpus_snapshot_id: str,
    latest_rows: dict[str, ResearchPanelRow],
    rows_by_accession: dict[str, ResearchPanelRow],
) -> str:
    required_features = _required_screen_features(plan)
    input_rows: list[dict[str, object]] = []
    for ticker in sorted(latest_rows):
        row = latest_rows[ticker]
        feature_inputs: dict[str, dict[str, str | None]] = {}
        prior_row = _prior_row(row, rows_by_accession)
        for feature in sorted(required_features):
            current_lineage = _required_feature_lineage(row, feature)
            needs_prior = any(
                condition.change_from_prior
                and _SCREEN_METRIC_FEATURE[condition.metric] == feature
                for condition in plan.conditions
            )
            prior_lineage = (
                _required_feature_lineage(prior_row, feature)
                if needs_prior and prior_row is not None
                else None
            )
            feature_inputs[feature] = {
                "current": current_lineage.lineage_id,
                "prior": prior_lineage.lineage_id if prior_lineage is not None else None,
            }
        input_rows.append(
            {
                "ticker": ticker,
                "accession_number": row.accession_number,
                "feature_inputs": feature_inputs,
            }
        )

    payload = json.dumps(
        {
            "plan_hash": plan_hash,
            "corpus_snapshot_id": corpus_snapshot_id,
            "feature_version": FEATURE_VERSION,
            "inputs": input_rows,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _required_screen_features(plan: ResearchScreenPlan) -> set[PanelFeature]:
    features = {
        _SCREEN_METRIC_FEATURE[condition.metric]
        for condition in plan.conditions
    }
    if plan.rank_by != "semantic_score":
        features.add(_SCREEN_METRIC_FEATURE[plan.rank_by])
    return features


def _aware_datetime(value: datetime, *, reference: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=reference.tzinfo)
    return value


def _plan_hash(plan: ResearchScreenPlan) -> str:
    payload = json.dumps(
        plan.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
