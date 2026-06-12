from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import Company
from fdre.retrieval.query import PreprocessedQuery, RouteName, SearchFilters

FORM_PATTERNS = {
    "10-K": re.compile(r"\b(?:10-k|annual report)\b", re.I),
    "10-Q": re.compile(r"\b(?:10-q|quarterly report)\b", re.I),
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

    base_filters = filters or SearchFilters()
    merged_filters = base_filters.model_copy(
        update={
            "tickers": sorted(set(base_filters.tickers) | detected_tickers),
            "form_types": sorted(set(base_filters.form_types) | set(detected_forms)),
            "sections": sorted(set(base_filters.sections) | set(detected_sections)),
            "element_types": sorted(
                set(base_filters.element_types) | set(element_types)
            ),
        }
    )
    finance_expansion = (
        f"{cleaned} SEC filing financial results risks management commentary"
    )
    section_query = (
        f"{cleaned} {' '.join(detected_sections)}" if detected_sections else cleaned
    )
    return PreprocessedQuery(
        original_query=cleaned,
        rewritten_queries=list(
            dict.fromkeys([cleaned, finance_expansion, section_query])
        ),
        filters=merged_filters,
        routes=list(dict.fromkeys(routes)),
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
