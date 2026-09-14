from __future__ import annotations

import hashlib
import json
import socket
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Company, Document, DocumentElement
from fdre.research.experiments.panel_replay import (
    RiskChurnPanelReplayInput,
    build_risk_churn_panel_replay_input,
    persist_risk_churn_panel_replay_input,
    replay_risk_churn_panel_input,
)
from fdre.research.panel import ResearchPanel, ResearchPanelQuery, build_research_panel


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _add_document(
    company: Company,
    *,
    accession: str,
    period_end: date,
    available_at: datetime,
    passages: list[str],
) -> Document:
    document = Document(
        company=company,
        source_type="sec",
        form_type="10-K",
        filing_date=available_at.date(),
        period_end_date=period_end,
        accepted_at=available_at,
        available_at=available_at,
        accession_number=accession,
        sha256_hash=_digest({"accession": accession, "passages": passages}),
    )
    for order, passage in enumerate(passages, start=1):
        document.elements.append(
            DocumentElement(
                element_type="text",
                section="Risk Factors",
                text=passage,
                reading_order=order,
            )
        )
    document.elements.append(
        DocumentElement(
            element_type="text",
            section="Business",
            text=f"Business description for {accession}",
            reading_order=len(passages) + 1,
        )
    )
    return document


def _source_panel(session: Session) -> ResearchPanel:
    company = Company(ticker="AAA", cik="0000000001", name="Alpha")
    _add_document(
        company,
        accession="aaa-2024",
        period_end=date(2024, 12, 31),
        available_at=datetime(2025, 2, 1, tzinfo=UTC),
        passages=["Common risk disclosure.", "Legacy supplier risk."],
    )
    _add_document(
        company,
        accession="aaa-2025",
        period_end=date(2025, 12, 31),
        available_at=datetime(2026, 2, 1, tzinfo=UTC),
        passages=["Common risk disclosure.", "New regulatory risk."],
    )
    outside = Company(ticker="ZZZ", cik="0000000002", name="Outside")
    _add_document(
        outside,
        accession="zzz-2025",
        period_end=date(2025, 12, 31),
        available_at=datetime(2026, 1, 1, tzinfo=UTC),
        passages=["Outside-scope risk."],
    )
    session.add_all([company, outside])
    session.commit()
    query = ResearchPanelQuery(
        tickers=["AAA"],
        form_types=["10-K"],
        features=["risk_changes"],
        as_of=datetime(2026, 6, 1, tzinfo=UTC),
    )
    return build_research_panel(session, query)


def test_panel_source_replay_reconstructs_exact_rows_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        panel = _source_panel(session)
        replay_input = build_risk_churn_panel_replay_input(session, panel)
        persist_risk_churn_panel_replay_input(session, replay_input)

    assert replay_input.row_accessions == ["aaa-2024", "aaa-2025"]
    assert {item.ticker for item in replay_input.companies} == {"AAA"}
    assert all(
        item.section == "Risk Factors" for item in replay_input.risk_factor_elements
    )
    assert all(
        "Business description" not in (item.text or "")
        for item in replay_input.risk_factor_elements
    )

    def _network_disabled(*args: object, **kwargs: object) -> None:
        raise AssertionError("panel replay attempted network access")

    monkeypatch.setattr(socket.socket, "connect", _network_disabled)
    replayed = replay_risk_churn_panel_input(replay_input)
    assert replayed.model_dump(mode="json") == panel.model_dump(mode="json")


def test_panel_source_replay_rejects_hash_consistent_element_forgery() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        panel = _source_panel(session)
        replay_input = build_risk_churn_panel_replay_input(session, panel)

    payload = replay_input.model_dump(mode="json")
    elements = cast(list[dict[str, Any]], payload["risk_factor_elements"])
    current_common = next(
        item
        for item in elements
        if item["text"] == "Common risk disclosure."
        and item["document_id"] == max(element["document_id"] for element in elements)
    )
    current_common["text"] = "Completely changed disclosure."
    payload["input_key"] = _digest(
        {key: value for key, value in payload.items() if key != "input_key"}
    )
    forged = RiskChurnPanelReplayInput.model_validate(payload)

    with pytest.raises(ValueError, match="panel replay row digest mismatch"):
        replay_risk_churn_panel_input(forged)


def test_panel_source_replay_rejects_scope_that_does_not_match_panel() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        panel = _source_panel(session)
        mismatched = panel.model_copy(
            update={
                "query": panel.query.model_copy(update={"tickers": ["AAA", "ZZZ"]})
            }
        )
        with pytest.raises(ValueError, match="does not reproduce panel row selection"):
            build_risk_churn_panel_replay_input(session, mismatched)
