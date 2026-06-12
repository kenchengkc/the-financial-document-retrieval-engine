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

__all__ = [
    "FilingDifference",
    "FinancialFactQuery",
    "FinancialFactRecord",
    "FinancialFactsResponse",
    "PassageChange",
    "compare_filing_to_prior",
    "diff_documents",
    "query_financial_facts",
    "select_comparable_document",
]
