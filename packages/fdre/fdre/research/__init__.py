"""Point-in-time research datasets and filing analysis."""

from fdre.research.event_study import (
    EventStudyConfig,
    EventStudyReport,
    EventWindow,
    FilingEvent,
    MarketBar,
    load_filing_events,
    load_market_bars,
    persist_event_study,
    run_event_study,
    validate_event_inputs,
    write_event_study_report,
)
from fdre.research.filing_diffs import (
    FilingDifference,
    PassageChange,
    compare_filing_to_prior,
    diff_documents,
    select_comparable_document,
)
from fdre.research.financial_facts import (
    FinancialFactQuery,
    FinancialFactRecord,
    FinancialFactsResponse,
    query_financial_facts,
)
from fdre.research.panel import (
    ResearchPanel,
    ResearchPanelQuery,
    ResearchPanelRow,
    build_research_panel,
    serialize_research_panel,
    validate_point_in_time_rows,
    write_research_panel,
)
from fdre.research.thematic import (
    ThematicIssuerResult,
    ThematicScanRequest,
    ThematicScanResponse,
    diversify_candidates_by_issuer,
)

__all__ = [
    "EventStudyConfig",
    "EventStudyReport",
    "EventWindow",
    "FilingDifference",
    "FilingEvent",
    "FinancialFactQuery",
    "FinancialFactRecord",
    "FinancialFactsResponse",
    "MarketBar",
    "PassageChange",
    "ResearchPanel",
    "ResearchPanelQuery",
    "ResearchPanelRow",
    "ThematicIssuerResult",
    "ThematicScanRequest",
    "ThematicScanResponse",
    "build_research_panel",
    "compare_filing_to_prior",
    "diff_documents",
    "diversify_candidates_by_issuer",
    "load_filing_events",
    "load_market_bars",
    "persist_event_study",
    "query_financial_facts",
    "run_event_study",
    "select_comparable_document",
    "serialize_research_panel",
    "validate_event_inputs",
    "validate_point_in_time_rows",
    "write_event_study_report",
    "write_research_panel",
]
