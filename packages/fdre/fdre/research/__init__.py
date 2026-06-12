"""Point-in-time research datasets and filing analysis."""

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
    validate_point_in_time_rows,
    write_research_panel,
)

__all__ = [
    "FilingDifference",
    "FinancialFactQuery",
    "FinancialFactRecord",
    "FinancialFactsResponse",
    "PassageChange",
    "ResearchPanel",
    "ResearchPanelQuery",
    "ResearchPanelRow",
    "build_research_panel",
    "compare_filing_to_prior",
    "diff_documents",
    "query_financial_facts",
    "select_comparable_document",
    "validate_point_in_time_rows",
    "write_research_panel",
]
