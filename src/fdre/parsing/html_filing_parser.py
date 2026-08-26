from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from bs4 import BeautifulSoup, Tag

from fdre.parsing.base import BaseDocumentParser, ElementType, ParsedElement

BLOCK_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "li", "table")
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

SECTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(?:item\s+1a\b[.:\s-]*)?risk factors?\b", re.I), "Risk Factors"),
    (re.compile(r"^item\s+1\b(?!a)[.:\s-]*business\b", re.I), "Business"),
    (re.compile(r"^business\b", re.I), "Business"),
    (re.compile(r"^(?:item\s+3\b[.:\s-]*)?legal proceedings?\b", re.I), "Legal Proceedings"),
    (
        re.compile(
            r"^(?:item\s+(?:2|7)\b[.:\s-]*(?:\|\s*)?)?"
            r"management(?:'|\u2019)s discussion and analysis\b",
            re.I,
        ),
        "MD&A",
    ),
    (
        re.compile(r"^(?:item\s+8\b[.:\s-]*)?financial statements\b", re.I),
        "Financial Statements",
    ),
    (
        re.compile(r"^(?:item\s+9a\b[.:\s-]*)?controls and procedures\b", re.I),
        "Controls and Procedures",
    ),
)


class HtmlFilingParser(BaseDocumentParser):
    """Extract ordered text and table elements from SEC filing HTML."""

    def parse(self, content: str | bytes) -> list[ParsedElement]:
        soup = BeautifulSoup(content, "lxml")
        self._remove_non_content(soup)
        root = soup.body or soup
        elements: list[ParsedElement] = []
        current_section: str | None = None
        last_signature: tuple[ElementType, str] | None = None

        document_title = _clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
        if _is_meaningful(document_title):
            last_signature = self._append(
                elements,
                element_type="title",
                text=document_title,
                section=None,
                metadata={"tag": "title"},
                last_signature=last_signature,
            )

        for tag in root.find_all(BLOCK_TAGS):
            if not isinstance(tag, Tag) or self._should_skip(tag):
                continue

            if tag.name == "table":
                text = _clean_text(tag.get_text(" ", strip=True))
                detected_section = _detect_section(text)
                if detected_section is not None and _looks_like_section_header(tag, text):
                    current_section = detected_section
                    last_signature = self._append(
                        elements,
                        element_type="section_header",
                        text=text,
                        section=detected_section,
                        metadata={"tag": tag.name},
                        last_signature=last_signature,
                    )
                    continue
                table = _parse_table(tag)
                if table is None:
                    continue
                last_signature = self._append(
                    elements,
                    element_type="table",
                    text=table["text"],
                    markdown=table["markdown"],
                    section=current_section,
                    metadata=table["metadata"],
                    last_signature=last_signature,
                )
                continue

            text = _clean_text(tag.get_text(" ", strip=True))
            if not _is_meaningful(text):
                continue

            detected_section = _detect_section(text)
            section: str | None
            if detected_section is not None and _looks_like_section_header(tag, text):
                current_section = detected_section
                element_type: ElementType = "section_header"
                section = detected_section
            elif tag.name in HEADING_TAGS:
                element_type = "title" if tag.name == "h1" and not elements else "section_header"
                section = current_section
            else:
                element_type = "text"
                section = current_section

            last_signature = self._append(
                elements,
                element_type=element_type,
                text=text,
                section=section,
                metadata={"tag": tag.name},
                last_signature=last_signature,
            )

        return elements

    @staticmethod
    def _remove_non_content(soup: BeautifulSoup) -> None:
        for tag in soup.find_all(["script", "style", "noscript", "template"]):
            tag.decompose()
        for tag in soup.find_all(True):
            # A parent decompose() also decomposes its children; skip tags that
            # were already removed (their attrs/name become None) to avoid
            # AttributeError on real-world nested filings.
            if not isinstance(tag, Tag) or tag.decomposed:
                continue
            name = tag.name.lower()
            style = str(tag.get("style", "")).lower().replace(" ", "")
            if (
                name.endswith(":hidden")
                or tag.has_attr("hidden")
                or str(tag.get("aria-hidden", "")).lower() == "true"
                or "display:none" in style
            ):
                tag.decompose()

    @staticmethod
    def _should_skip(tag: Tag) -> bool:
        if tag.name == "table":
            return tag.find_parent("table") is not None
        if tag.find_parent("table") is not None:
            return True
        if tag.name == "div":
            return tag.find(BLOCK_TAGS, recursive=False) is not None
        return False

    @staticmethod
    def _append(
        elements: list[ParsedElement],
        *,
        element_type: ElementType,
        text: str,
        section: str | None,
        metadata: dict[str, Any],
        last_signature: tuple[ElementType, str] | None,
        markdown: str | None = None,
    ) -> tuple[ElementType, str]:
        signature = (element_type, text)
        if signature == last_signature:
            return signature
        elements.append(
            ParsedElement(
                element_type=element_type,
                text=text,
                markdown=markdown,
                section=section,
                reading_order=len(elements),
                metadata=metadata,
            )
        )
        return signature


def _detect_section(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text).strip()
    note_match = re.match(r"^note\s+(\d+[a-z]?)\s*[\u2014\u2013-]\s*(.+)$", normalized, re.I)
    if note_match:
        title = note_match.group(2).strip()
        return f"Note {note_match.group(1)} \u2014 {title}"
    for pattern, section in SECTION_PATTERNS:
        if pattern.search(normalized):
            return section
    return None


def _looks_like_section_header(tag: Tag, text: str) -> bool:
    return tag.name in HEADING_TAGS or (
        len(text) <= 220
        and (
            re.match(r"^item\s+\d+[a-z]?\b", text, re.I) is not None
            or re.match(r"^note\s+\d+[a-z]?\s*[\u2014\u2013-]\s*.+", text, re.I) is not None
            or text.casefold()
            in {
                "business",
                "risk factors",
                "legal proceedings",
                "management's discussion and analysis",
                "financial statements",
                "controls and procedures",
            }
        )
    )


def _parse_table(table: Tag) -> dict[str, Any] | None:
    rows: list[list[str]] = []
    for row in table.find_all("tr"):
        cells = [
            _clean_text(cell.get_text(" ", strip=True))
            for cell in row.find_all(["th", "td"], recursive=False)
        ]
        if any(_is_meaningful(cell) for cell in cells):
            rows.append(cells)

    if not rows:
        return None

    column_count = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
    headers = normalized_rows[0]
    body = normalized_rows[1:]
    markdown_lines = [
        _markdown_row(headers),
        _markdown_row(["---"] * column_count),
        *(_markdown_row(row) for row in body),
    ]
    text = "\n".join(" | ".join(cell for cell in row if cell) for row in normalized_rows)
    return {
        "text": text,
        "markdown": "\n".join(markdown_lines),
        "metadata": {
            "tag": "table",
            "row_count": len(body),
            "column_count": column_count,
            "headers": headers,
        },
    }


def _markdown_row(cells: Iterable[str]) -> str:
    escaped = [cell.replace("|", "\\|").replace("\n", " ") for cell in cells]
    return f"| {' | '.join(escaped)} |"


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u200b", " ")).strip()


def _is_meaningful(text: str) -> bool:
    return bool(text and any(character.isalnum() for character in text))
