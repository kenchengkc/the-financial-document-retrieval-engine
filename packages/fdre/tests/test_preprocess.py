from fdre.retrieval.preprocess import CompanyReference, preprocess_query

COMPANIES = [
    CompanyReference(ticker="AAPL", name="Apple Inc."),
    CompanyReference(ticker="MSFT", name="Microsoft Corporation"),
    CompanyReference(ticker="NVDA", name="NVIDIA Corporation"),
]


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
