"""Offline reconstruction of flagship PIT panel rows from persisted SEC-derived inputs.

This layer deliberately starts from FDRE's persisted document metadata and parsed
Risk Factors elements. It does not claim to reproduce SEC download or parsing from
raw filing bytes; that remains a separate upstream reproducibility boundary.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.models import Company, Document, DocumentElement, ResearchExperiment
from fdre.research.filing_diffs import select_comparable_document_from_candidates
from fdre.research.panel import (
    FEATURE_VERSION,
    PanelElement,
    ResearchPanel,
    ResearchPanelQuery,
    _build_row,
    _corpus_snapshot_id,
    _latest_documents_with_priors,
    validate_point_in_time_rows,
)

_PANEL_REPLAY_VERSION = "risk-churn-panel-replay-input-v1"


class PanelSourceCompany(BaseModel):
    id: int
    ticker: str | None
    cik: str
    name: str


class PanelSourceDocument(BaseModel):
    id: int
    company_id: int
    source_type: str
    form_type: str
    filing_date: date | None
    period_end_date: date | None
    accepted_at: datetime | None
    available_at: datetime | None
    is_amendment: bool
    amends_accession_number: str | None
    accession_number: str
    sha256_hash: str | None


class PanelSourceElement(BaseModel):
    id: int
    document_id: int
    element_type: str
    section: str | None
    text: str | None
    markdown: str | None
    reading_order: int | None


class RiskChurnPanelReplayInput(BaseModel):
    """Content-addressed persisted inputs needed to reconstruct risk-churn panel rows."""

    input_key: str
    replay_input_version: str = _PANEL_REPLAY_VERSION
    panel_feature_version: str = FEATURE_VERSION
    query: ResearchPanelQuery
    latest_with_priors_only: bool = False
    corpus_snapshot_id: str
    row_accessions: list[str]
    companies: list[PanelSourceCompany]
    documents: list[PanelSourceDocument]
    risk_factor_elements: list[PanelSourceElement]


def build_risk_churn_panel_replay_input(
    session: Session,
    panel: ResearchPanel,
    *,
    latest_with_priors_only: bool = False,
) -> RiskChurnPanelReplayInput:
    """Freeze the exact persisted corpus needed to reconstruct a risk-churn panel.

    The query scope must be explicit so the frozen metadata can independently
    reconstruct row selection rather than trusting a preselected accession list.
    """

    _validate_supported_query(panel.query)
    if panel.feature_version != FEATURE_VERSION:
        raise ValueError("risk-churn panel replay feature version mismatch")

    companies = _load_scoped_companies(session, panel.query)
    company_ids = {company.id for company in companies}
    if not company_ids:
        raise ValueError("risk-churn panel replay query scope contains no companies")
    documents = list(
        session.scalars(
            select(Document)
            .options(joinedload(Document.company))
            .where(Document.company_id.in_(company_ids))
            .order_by(Document.id)
        ).unique()
    )
    selected_documents, prior_by_document = _select_panel_documents(
        documents,
        panel.query,
        latest_with_priors_only=latest_with_priors_only,
    )
    row_accessions = [document.accession_number for document in selected_documents]
    expected_accessions = [row.accession_number for row in panel.rows]
    if row_accessions != expected_accessions:
        raise ValueError("persisted document scope does not reproduce panel row selection")

    source_documents_by_id = {document.id: document for document in selected_documents}
    for document in selected_documents:
        prior = prior_by_document[document.id]
        if prior is not None:
            source_documents_by_id[prior.id] = prior
    source_documents = list(source_documents_by_id.values())
    snapshot_id = _corpus_snapshot_id(source_documents)
    if snapshot_id != panel.corpus_snapshot_id:
        raise ValueError("persisted document scope does not reproduce panel corpus snapshot")

    source_document_ids = set(source_documents_by_id)
    risk_factor_elements = list(
        session.execute(
            select(
                DocumentElement.id,
                DocumentElement.document_id,
                DocumentElement.element_type,
                DocumentElement.section,
                DocumentElement.text,
                DocumentElement.markdown,
                DocumentElement.reading_order,
            )
            .where(
                DocumentElement.document_id.in_(source_document_ids),
                DocumentElement.section == "Risk Factors",
            )
            .order_by(
                DocumentElement.document_id,
                DocumentElement.reading_order,
                DocumentElement.id,
            )
        )
    )

    payload: dict[str, Any] = {
        "replay_input_version": _PANEL_REPLAY_VERSION,
        "panel_feature_version": FEATURE_VERSION,
        "query": panel.query.model_dump(mode="json"),
        "latest_with_priors_only": latest_with_priors_only,
        "corpus_snapshot_id": panel.corpus_snapshot_id,
        "row_accessions": row_accessions,
        "companies": [
            PanelSourceCompany(
                id=company.id,
                ticker=company.ticker,
                cik=company.cik,
                name=company.name,
            ).model_dump(mode="json")
            for company in companies
        ],
        "documents": [
            _freeze_document(document).model_dump(mode="json") for document in documents
        ],
        "risk_factor_elements": [
            PanelSourceElement(
                id=element_id,
                document_id=document_id,
                element_type=element_type,
                section=section,
                text=text,
                markdown=markdown,
                reading_order=reading_order,
            ).model_dump(mode="json")
            for (
                element_id,
                document_id,
                element_type,
                section,
                text,
                markdown,
                reading_order,
            ) in risk_factor_elements
        ],
    }
    replay_input = RiskChurnPanelReplayInput(
        input_key=_stable_digest(payload),
        **payload,
    )
    replayed = replay_risk_churn_panel_input(replay_input)
    if replayed.model_dump(mode="json") != panel.model_dump(mode="json"):
        raise ValueError("persisted panel source input does not reproduce the supplied panel")
    return replay_input


def replay_risk_churn_panel_input(
    replay_input: RiskChurnPanelReplayInput,
) -> ResearchPanel:
    """Reconstruct risk-churn PIT panel rows without database or provider access."""

    if _panel_input_identity(replay_input) != replay_input.input_key:
        raise ValueError("risk-churn panel replay input digest mismatch")
    if replay_input.replay_input_version != _PANEL_REPLAY_VERSION:
        raise ValueError("risk-churn panel replay input version mismatch")
    if replay_input.panel_feature_version != FEATURE_VERSION:
        raise ValueError("risk-churn panel replay feature version mismatch")
    _validate_supported_query(replay_input.query)

    companies = {
        item.id: Company(
            id=item.id,
            ticker=item.ticker,
            cik=item.cik,
            name=item.name,
        )
        for item in replay_input.companies
    }
    if len(companies) != len(replay_input.companies):
        raise ValueError("risk-churn panel replay contains duplicate company ids")

    documents: list[Document] = []
    seen_document_ids: set[int] = set()
    seen_accessions: set[str] = set()
    for item in replay_input.documents:
        if item.id in seen_document_ids:
            raise ValueError("risk-churn panel replay contains duplicate document ids")
        if item.accession_number in seen_accessions:
            raise ValueError("risk-churn panel replay contains duplicate accessions")
        company = companies.get(item.company_id)
        if company is None:
            raise ValueError("risk-churn panel replay document references unknown company")
        seen_document_ids.add(item.id)
        seen_accessions.add(item.accession_number)
        documents.append(_thaw_document(item, company))

    selected_documents, prior_by_document = _select_panel_documents(
        documents,
        replay_input.query,
        latest_with_priors_only=replay_input.latest_with_priors_only,
    )
    row_accessions = [document.accession_number for document in selected_documents]
    if row_accessions != replay_input.row_accessions:
        raise ValueError("risk-churn panel replay row selection mismatch")

    source_documents_by_id = {document.id: document for document in selected_documents}
    for document in selected_documents:
        prior = prior_by_document[document.id]
        if prior is not None:
            source_documents_by_id[prior.id] = prior
    snapshot_id = _corpus_snapshot_id(list(source_documents_by_id.values()))
    if snapshot_id != replay_input.corpus_snapshot_id:
        raise ValueError("risk-churn panel replay corpus snapshot mismatch")

    source_document_ids = set(source_documents_by_id)
    elements_by_document: dict[int, list[PanelElement]] = defaultdict(list)
    seen_element_ids: set[int] = set()
    for item in replay_input.risk_factor_elements:
        if item.id in seen_element_ids:
            raise ValueError("risk-churn panel replay contains duplicate element ids")
        if item.document_id not in source_document_ids:
            raise ValueError("risk-churn panel replay element references a non-source document")
        if item.section != "Risk Factors":
            raise ValueError("risk-churn panel replay contains a non-Risk-Factors element")
        seen_element_ids.add(item.id)
        elements_by_document[item.document_id].append(
            PanelElement(
                document_id=item.document_id,
                element_type=item.element_type,
                section=item.section,
                text=item.text,
                markdown=item.markdown,
            )
        )

    rows = [
        _build_row(
            document,
            query=replay_input.query,
            snapshot_id=snapshot_id,
            prior=prior_by_document[document.id],
            elements_by_document=dict(elements_by_document),
            facts_by_document={},
        )
        for document in selected_documents
    ]
    validate_point_in_time_rows(rows)
    return ResearchPanel(
        query=replay_input.query,
        feature_version=FEATURE_VERSION,
        corpus_snapshot_id=snapshot_id,
        rows=rows,
    )


def persist_risk_churn_panel_replay_input(
    session: Session,
    replay_input: RiskChurnPanelReplayInput,
) -> ResearchExperiment:
    """Persist a content-addressed panel-source replay input immutably."""

    if _panel_input_identity(replay_input) != replay_input.input_key:
        raise ValueError("risk-churn panel replay input digest mismatch")
    payload = replay_input.model_dump(mode="json")
    experiment = session.scalar(
        select(ResearchExperiment).where(
            ResearchExperiment.experiment_key == replay_input.input_key
        )
    )
    if experiment is None:
        experiment = ResearchExperiment(
            experiment_key=replay_input.input_key,
            experiment_type="risk_churn_panel_replay_input",
            dataset_version=f"panel:{replay_input.corpus_snapshot_id}",
            feature_version=replay_input.panel_feature_version,
            code_sha="deterministic-panel-replay",
            config_json={
                "replay_input_version": replay_input.replay_input_version,
                "corpus_snapshot_id": replay_input.corpus_snapshot_id,
                "row_count": len(replay_input.row_accessions),
            },
            results_json=payload,
        )
        session.add(experiment)
    elif experiment.results_json != payload:
        raise ValueError("risk-churn panel replay input payload mismatch")
    else:
        return experiment
    session.commit()
    session.refresh(experiment)
    return experiment


def write_risk_churn_panel_replay_input(
    path: str | Path,
    replay_input: RiskChurnPanelReplayInput,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(replay_input.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    return destination


def _validate_supported_query(query: ResearchPanelQuery) -> None:
    selected_features = set(query.features)
    if selected_features != {"risk_changes"}:
        raise ValueError("risk-churn panel replay requires only the risk_changes feature")
    if query.sections:
        raise ValueError("risk-churn panel replay v1 requires the full Risk Factors section")
    if not query.tickers and not query.ciks:
        raise ValueError("risk-churn panel replay requires an explicit ticker or CIK scope")


def _load_scoped_companies(session: Session, query: ResearchPanelQuery) -> list[Company]:
    statement = select(Company).order_by(Company.id)
    if query.tickers:
        statement = statement.where(
            Company.ticker.in_([ticker.upper() for ticker in query.tickers])
        )
    if query.ciks:
        statement = statement.where(Company.cik.in_(query.ciks))
    return list(session.scalars(statement))


def _select_panel_documents(
    documents: list[Document],
    query: ResearchPanelQuery,
    *,
    latest_with_priors_only: bool,
) -> tuple[list[Document], dict[int, Document | None]]:
    tickers = {ticker.upper() for ticker in query.tickers}
    ciks = set(query.ciks)
    form_types = {form.upper() for form in query.form_types}
    selected = [
        document
        for document in documents
        if document.available_at is not None
        and document.period_end_date is not None
        and (not tickers or (document.company.ticker or "").upper() in tickers)
        and (not ciks or document.company.cik in ciks)
        and (not form_types or document.form_type.upper() in form_types)
        and (query.period_end_from is None or document.period_end_date >= query.period_end_from)
        and (query.period_end_to is None or document.period_end_date <= query.period_end_to)
        and (query.as_of is None or document.available_at <= query.as_of)
        and (query.include_amendments or not document.is_amendment)
    ]
    selected.sort(key=lambda document: (document.available_at, document.id))
    selected = selected[: query.limit]

    documents_by_company: dict[int, list[Document]] = defaultdict(list)
    for document in documents:
        documents_by_company[document.company_id].append(document)
    prior_by_document: dict[int, Document | None] = {}
    for document in selected:
        prior, _ = select_comparable_document_from_candidates(
            document,
            documents_by_company[document.company_id],
            as_of=document.available_at,
        )
        prior_by_document[document.id] = prior
    if latest_with_priors_only:
        selected = _latest_documents_with_priors(selected, prior_by_document)
    return selected, prior_by_document


def _freeze_document(document: Document) -> PanelSourceDocument:
    return PanelSourceDocument(
        id=document.id,
        company_id=document.company_id,
        source_type=document.source_type,
        form_type=document.form_type,
        filing_date=document.filing_date,
        period_end_date=document.period_end_date,
        accepted_at=document.accepted_at,
        available_at=document.available_at,
        is_amendment=document.is_amendment,
        amends_accession_number=document.amends_accession_number,
        accession_number=document.accession_number,
        sha256_hash=document.sha256_hash,
    )


def _thaw_document(item: PanelSourceDocument, company: Company) -> Document:
    return Document(
        id=item.id,
        company_id=item.company_id,
        company=company,
        source_type=item.source_type,
        form_type=item.form_type,
        filing_date=item.filing_date,
        period_end_date=item.period_end_date,
        accepted_at=item.accepted_at,
        available_at=item.available_at,
        is_amendment=item.is_amendment,
        amends_accession_number=item.amends_accession_number,
        accession_number=item.accession_number,
        sha256_hash=item.sha256_hash,
    )


def _panel_input_identity(replay_input: RiskChurnPanelReplayInput) -> str:
    return _stable_digest(replay_input.model_dump(mode="json", exclude={"input_key"}))


def _stable_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
