"""Compose research panels from point-in-time Historical Universe snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time

from sqlalchemy.orm import Session

from fdre.research.historical_universe import UniverseSnapshot
from fdre.research.panel import (
    ResearchPanel,
    ResearchPanelQuery,
    build_research_panel,
    empty_research_panel,
)
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

    Filings are issuer disclosures, so selection is keyed by the snapshot's stable SEC CIKs rather
    than present-day ticker aliases. This admits historical-only issuers without inventing a
    current ticker. The exact universe snapshot remains attached to the result so downstream
    experiments can persist its ``snapshot_id``.
    """

    snapshot = universe_from_session(
        session,
        universe_code,
        as_of=as_of,
        include_provisional=include_provisional,
    )
    ciks = tuple(sorted({row.cik for row in snapshot.constituents}))
    base_query = query or ResearchPanelQuery()
    panel_as_of = datetime.combine(snapshot.as_of, time.max, tzinfo=UTC)
    composed_query = base_query.model_copy(
        update={
            "tickers": [],
            "ciks": list(ciks),
            "as_of": panel_as_of,
        }
    )
    panel = (
        build_research_panel(session, composed_query)
        if ciks
        else empty_research_panel(composed_query)
    )
    return UniverseResearchPanel(universe_snapshot=snapshot, panel=panel)
