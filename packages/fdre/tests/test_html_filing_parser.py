from __future__ import annotations

from pathlib import Path

from fdre.parsing.html_filing_parser import HtmlFilingParser

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "data/sample/sec_filing.html"


def test_extracts_sections_text_tables_and_reading_order() -> None:
    elements = HtmlFilingParser().parse_file(FIXTURE_PATH)

    assert elements
    assert [element.reading_order for element in elements] == list(range(len(elements)))
    assert all((element.text or element.markdown or "").strip() for element in elements)
    assert not any("ignoreThis" in (element.text or "") for element in elements)
    assert not any("Hidden filing metadata" in (element.text or "") for element in elements)

    sections = {
        element.section
        for element in elements
        if element.element_type == "section_header"
    }
    assert {"Business", "Risk Factors", "MD&A", "Financial Statements"} <= sections

    risk_text = next(
        element
        for element in elements
        if element.element_type == "text" and "Market volatility" in (element.text or "")
    )
    assert risk_text.section == "Risk Factors"

    tables = [element for element in elements if element.element_type == "table"]
    assert len(tables) == 1
    assert tables[0].section == "Risk Factors"
    assert tables[0].markdown == (
        "| Year | Revenue |\n"
        "| --- | --- |\n"
        "| 2025 | $125 |\n"
        "| 2024 | $100 |"
    )
    assert tables[0].metadata["row_count"] == 2
    assert tables[0].metadata["column_count"] == 2


def test_removes_nested_hidden_tags_without_crashing() -> None:
    elements = HtmlFilingParser().parse(
        """
        <html>
          <body>
            <div style="display: none">
              <span><strong>Hidden filing metadata</strong></span>
            </div>
            <p>Visible filing content.</p>
          </body>
        </html>
        """
    )

    texts = [element.text for element in elements]
    assert "Visible filing content." in texts
    assert not any("Hidden filing metadata" in (text or "") for text in texts)


def test_detects_sections_encoded_as_layout_tables() -> None:
    elements = HtmlFilingParser().parse(
        """
        <html>
          <body>
            <table>
              <tr><td>Item 3.</td><td>Legal Proceedings</td></tr>
            </table>
            <p>We are involved in legal matters.</p>
            <table>
              <tr><td>Item 1A.</td><td>Risk Factors</td></tr>
            </table>
            <p>Competition may reduce sales and profits.</p>
          </body>
        </html>
        """
    )

    risk_header = next(
        element
        for element in elements
        if element.element_type == "section_header" and element.section == "Risk Factors"
    )
    assert risk_header.text == "Item 1A. Risk Factors"
    risk_text = next(
        element
        for element in elements
        if element.element_type == "text" and "Competition" in (element.text or "")
    )
    assert risk_text.section == "Risk Factors"
