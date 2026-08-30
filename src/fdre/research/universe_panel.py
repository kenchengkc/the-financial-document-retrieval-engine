"""Compose research panels from point-in-time Historical Universe snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.companies import Company
from fdre.research.historical_universe import UniverseSnapshot
from fdre.research.panel import ResearchPanel, ResearchPanelQuery, build_research_panel
from fdre.universe import universe_from_session


@dataclass(frozen=True, slots=True)
class UniverseResearchPanel:
    """Research panel paired with the exact universe snapshot that selected its issuers."""

    universe_snapshot: UniverseSnapshot
    panel: ResearchPanel


def build_research_panel_for_universe(
    session: Session,
    universe_code: str,
    *,
    as_of: str,
    include_provisional: bool = False,
    query: ResearchPanelQuery | None = None,
) -> UniverseResearchPanel:
    """Build a filing panel from the issuer CIKs selected by a PIT universe.

    The existing panel contract filters on ingestion tickers, so this adapter first maps every
    snapshot CIK to its current ingestion-catalog ticker. Missing mappings fail closed instead of
    silently shrinking the historical universe. The exact universe snapshot remains attached to
    the result so downstream experiments can persist its ``snapshot_id``.
    """

    snapshot = universe_from_session(
        session,
        universe_code,
        as_of=as_of,
        include_provisional=include_provisional,
    )
    ciks = tuple(sorted({row.cik for row in snapshot.constituents}))
    rows = session.execute(
        select(Company.cik, Company.ticker)
        .where(Company.cik.in_(ciks))
        .order_by(Company.cik)
    ).all() if ciks else []
    ticker_by_cik = {
        str(row.cik): str(row.ticker)
        for row in rows
        if row.ticker is not None and str(row.ticker).strip()
    }
    missing_ciks = tuple(sorted(set(ciks) - set(ticker_by_cik)))
    if missing_ciks:
        raise ValueError(
            "universe constituents lack ingestion ticker mappings: " + ", ".join(missing_ciks)
        )

    base_query = query or ResearchPanelQuery()
    panel_as_of = datetime.combine(snapshot.as_of, time.max, tzinfo=UTC)
    composed_query = base_query.model_copy(
        update={
            "tickers": sorted(set(ticker_by_cik.values())),
            "as_of": panel_as_of,
        }
    )
    panel = build_research_panel(session, composed_query)
    return UniverseResearchPanel(universe_snapshot=snapshot, panel=panel)
