from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import Chunk, Company, Document
from fdre.retrieval.query import PreprocessedQuery, RouteName, SearchFilters

FORM_PATTERNS = {
    "10-K": re.compile(r"\b(?:10-k|annual report)\b", re.I),
    "10-Q": re.compile(
        r"\b(?:10-q|quarterly report|last quarter|latest quarter)\b",
        re.I,
    ),
    "8-K": re.compile(r"\b8-k\b", re.I),
}
SECTION_PATTERNS = {
    "Risk Factors": re.compile(r"\brisk factors?\b", re.I),
    "MD&A": re.compile(r"\b(?:md&a|management(?:'s|\u2019s) discussion)\b", re.I),
    "Business": re.compile(r"\bbusiness\b", re.I),
    "Financial Statements": re.compile(r"\bfinancial statements?\b", re.I),
    "Legal Proceedings": re.compile(r"\blegal proceedings?\b", re.I),
    "Controls and Procedures": re.compile(r"\bcontrols?(?: and procedures)?\b", re.I),
}
TABLE_PATTERN = re.compile(r"\b(?:table|tabular|rows?|columns?|segment revenue)\b", re.I)
FIGURE_PATTERN = re.compile(r"\b(?:chart|figure|graph)\b", re.I)
FACT_PATTERN = re.compile(
    r"\b(?:revenue|net income|assets|liabilities|growth|margin|cash flow|compare)\b",
    re.I,
)
FINANCIAL_RESULTS_PATTERN = re.compile(
    r"\b(?:earnings|eps|financial results?|quarterly results?)\b",
    re.I,
)
LATEST_FILING_PATTERN = re.compile(r"\b(?:latest|most recent|last)\b", re.I)
YEAR_PATTERN = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


@dataclass(frozen=True, slots=True)
class CompanyReference:
    ticker: str
    name: str


def load_company_references(session: Session) -> list[CompanyReference]:
    return [
        CompanyReference(ticker=company.ticker, name=company.name)
        for company in session.scalars(select(Company).order_by(Company.ticker))
    ]


def preprocess_query(
    query: str,
    *,
    companies: Iterable[CompanyReference] = (),
    filters: SearchFilters | None = None,
) -> PreprocessedQuery:
    cleaned = " ".join(query.split())
    if not cleaned:
        raise ValueError("query must not be empty")
    company_list = list(companies)
    known_tickers = {company.ticker.upper() for company in company_list}
    detected_tickers = {
        token
        for token in re.findall(r"\b[A-Z]{1,5}\b", cleaned)
        if token in known_tickers
    }
    normalized_query = _normalize_company_text(cleaned)
    alias_owners: dict[str, set[str]] = {}
    for company in company_list:
        for alias in _company_aliases(company.name):
            alias_owners.setdefault(alias, set()).add(company.ticker.upper())
    for alias, owners in alias_owners.items():
        if len(owners) == 1 and _contains_alias(normalized_query, alias):
            detected_tickers.update(owners)

    detected_forms = [
        form_type for form_type, pattern in FORM_PATTERNS.items() if pattern.search(cleaned)
    ]
    detected_sections = [
        section for section, pattern in SECTION_PATTERNS.items() if pattern.search(cleaned)
    ]
    element_types: list[str] = []
    routes: list[RouteName] = ["text"]
    if TABLE_PATTERN.search(cleaned):
        element_types.append("table")
        routes.append("tables")
    if FIGURE_PATTERN.search(cleaned):
        element_types.append("figure")
    if FACT_PATTERN.search(cleaned):
        routes.append("financial_facts")
    if FINANCIAL_RESULTS_PATTERN.search(cleaned):
        routes.extend(["tables", "financial_facts"])

    base_filters = filters or SearchFilters()
    detected_years = sorted({int(value) for value in YEAR_PATTERN.findall(cleaned)})
    date_updates: dict[str, date] = {}
    if (
        detected_years
        and base_filters.filing_date_from is None
        and base_filters.filing_date_to is None
    ):
        date_updates = {
            "filing_date_from": date(min(detected_years), 1, 1),
            "filing_date_to": date(max(detected_years), 12, 31),
        }
    merged_filters = base_filters.model_copy(
        update={
            "tickers": sorted(set(base_filters.tickers) | detected_tickers),
            "form_types": sorted(set(base_filters.form_types) | set(detected_forms)),
            "sections": sorted(set(base_filters.sections) | set(detected_sections)),
            "element_types": sorted(
                set(base_filters.element_types) | set(element_types)
            ),
            **date_updates,
        }
    )
    section_query = (
        f"{cleaned} {' '.join(detected_sections)}" if detected_sections else cleaned
    )
    # Expand detected tickers to their issuer names so a ticker-only query
    # ("AAPL margins") also matches passages that spell out "Apple Inc".
    ticker_names = {company.ticker.upper(): company.name for company in company_list}
    company_terms = " ".join(
        ticker_names[ticker]
        for ticker in sorted(detected_tickers)
        if ticker in ticker_names
    )
    company_expansion = (
        f"{cleaned} {company_terms}".strip() if company_terms else cleaned
    )
    rewritten = [cleaned, company_expansion, section_query]
    # Finance-suffix expansion helps single-name recall, but on unfiltered
    # thematic queries it doubles full-corpus dense+sparse work for little gain.
    if merged_filters.tickers:
        rewritten.append(
            f"{cleaned} SEC filing financial results risks management commentary"
        )
    return PreprocessedQuery(
        original_query=cleaned,
        rewritten_queries=list(dict.fromkeys(rewritten)),
        filters=merged_filters,
        routes=list(dict.fromkeys(routes)),
    )


def apply_latest_filing_filter(
    session: Session,
    query: str,
    preprocessed: PreprocessedQuery,
) -> PreprocessedQuery:
    """Constrain a single-issuer query to its newest indexed filing.

    A global filing-date sort is not enough: repeated disclosure can make an
    older filing outrank the current one. Only resolve unambiguous issuer/form
    queries, and preserve explicit date bounds supplied by API callers.
    """
    filters = preprocessed.filters
    if (
        not LATEST_FILING_PATTERN.search(query)
        or len(filters.tickers) != 1
        or len(filters.form_types) != 1
        or filters.filing_date_from is not None
        or filters.filing_date_to is not None
    ):
        return preprocessed

    statement = (
        select(Document.filing_date)
        .join(Company, Document.company_id == Company.id)
        .join(Chunk, Chunk.document_id == Document.id)
        .where(
            Company.ticker == filters.tickers[0],
            Document.form_type == filters.form_types[0],
            Document.filing_date.is_not(None),
        )
    )
    if filters.as_of is not None:
        statement = statement.where(Document.available_at <= filters.as_of)
    if filters.amendment_policy == "exclude":
        statement = statement.where(Document.is_amendment.is_(False))
    elif filters.amendment_policy == "only":
        statement = statement.where(Document.is_amendment.is_(True))

    latest_date = session.scalar(
        statement.order_by(
            Document.filing_date.desc(),
            Document.accepted_at.desc(),
        ).limit(1)
    )
    if latest_date is None:
        return preprocessed

    return preprocessed.model_copy(
        update={
            "filters": filters.model_copy(
                update={
                    "filing_date_from": latest_date,
                    "filing_date_to": latest_date,
                }
            )
        }
    )


_COMPANY_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "limited",
    "ltd",
    "plc",
}
_AMBIGUOUS_SINGLE_WORD_ALIASES = {
    "a",
    "all",
    "are",
    "at",
    "best",
    "block",
    "c",
    "day",
    "dollar",
    "general",
    "global",
    "international",
    "on",
    "one",
    "target",
    "the",
    "trade",
    "united",
}


def _normalize_company_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", normalized))


def _company_aliases(name: str) -> set[str]:
    normalized = _normalize_company_text(name)
    tokens = normalized.split()
    while tokens and tokens[-1] in _COMPANY_SUFFIXES:
        tokens.pop()
    aliases = {normalized, " ".join(tokens)}
    if tokens:
        first = tokens[0]
        if len(first) >= 3 and first not in _AMBIGUOUS_SINGLE_WORD_ALIASES:
            aliases.add(first)
    return {alias for alias in aliases if alias}


def _contains_alias(normalized_query: str, alias: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalized_query) is not None
