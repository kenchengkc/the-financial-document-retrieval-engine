from datetime import date

from fdre.retrieval.preprocess import CompanyReference, preprocess_query
from fdre.retrieval.query import SearchFilters

COMPANIES = [
    CompanyReference(ticker="AAPL", name="Apple Inc."),
    CompanyReference(ticker="MSFT", name="Microsoft Corporation"),
    CompanyReference(ticker="NVDA", name="NVIDIA Corporation"),
    CompanyReference(ticker="ON", name="ON Semiconductor Corporation"),
    CompanyReference(ticker="PPL", name="PPL Corporation"),
    CompanyReference(ticker="TEL", name="TE Connectivity plc"),
]


def test_preprocess_expands_ticker_to_company_name() -> None:
    result = preprocess_query("AAPL gross margin trend", companies=COMPANIES)
    assert result.filters.tickers == ["AAPL"]
    # one rewrite spells out the issuer name so ticker-only queries still match
    assert any("Apple Inc." in variant for variant in result.rewritten_queries)


def test_preprocess_resolves_company_section_and_form() -> None:
    result = preprocess_query(
        "What changed in Apple's risk factors in the annual report?",
        companies=COMPANIES,
    )
    assert result.filters.tickers == ["AAPL"]
    assert result.filters.sections == ["Risk Factors"]
    assert result.filters.form_types == ["10-K"]
    assert len(result.rewritten_queries) >= 2


def test_preprocess_routes_table_and_financial_fact_queries() -> None:
    table = preprocess_query(
        "Find the table showing Nvidia segment revenue",
        companies=COMPANIES,
    )
    comparison = preprocess_query(
        "Compare Microsoft revenue growth with cloud demand commentary",
        companies=COMPANIES,
    )
    assert table.filters.tickers == ["NVDA"]
    assert table.filters.element_types == ["table"]
    assert "tables" in table.routes
    assert comparison.filters.tickers == ["MSFT"]
    assert "financial_facts" in comparison.routes


def test_preprocess_routes_earnings_queries_without_forcing_table_filter() -> None:
    result = preprocess_query(
        "What did META report for earnings last quarter?",
        companies=[*COMPANIES, CompanyReference(ticker="META", name="Meta Platforms, Inc.")],
    )

    assert result.filters.tickers == ["META"]
    assert result.filters.form_types == ["10-Q"]
    assert result.filters.element_types == []
    assert result.routes == ["text", "tables", "financial_facts"]


def test_preprocess_does_not_match_company_names_inside_words() -> None:
    result = preprocess_query(
        "What did Apple say about supply chain risk in its latest 10-K?",
        companies=COMPANIES,
    )

    assert result.filters.tickers == ["AAPL"]


def test_preprocess_leaves_cross_sectional_theme_queries_unfiltered() -> None:
    result = preprocess_query(
        "Which companies mention data center power constraints?",
        companies=COMPANIES,
    )

    assert result.filters.tickers == []
    assert result.rewritten_queries == [
        "Which companies mention data center power constraints?"
    ]


def test_preprocess_keeps_finance_expansion_for_ticker_queries() -> None:
    result = preprocess_query("AAPL gross margin trend", companies=COMPANIES)

    assert any(
        "SEC filing financial results" in variant for variant in result.rewritten_queries
    )


def test_preprocess_converts_explicit_years_to_filing_date_bounds() -> None:
    result = preprocess_query(
        "Compare Apple's 2022 and 2023 annual reports",
        companies=COMPANIES,
    )

    assert result.filters.filing_date_from == date(2022, 1, 1)
    assert result.filters.filing_date_to == date(2023, 12, 31)


def test_preprocess_preserves_caller_date_bounds() -> None:
    filters = SearchFilters(
        filing_date_from=date(2024, 2, 1),
        filing_date_to=date(2024, 3, 1),
    )
    result = preprocess_query(
        "What did Apple disclose in 2022?",
        companies=COMPANIES,
        filters=filters,
    )

    assert result.filters.filing_date_from == filters.filing_date_from
    assert result.filters.filing_date_to == filters.filing_date_to
