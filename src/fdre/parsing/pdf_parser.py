from __future__ import annotations

from fdre.parsing.base import BaseDocumentParser, ParsedElement


class PdfParser(BaseDocumentParser):
    """Reserved extension point for a future layout-aware PDF provider."""

    def parse(self, content: str | bytes) -> list[ParsedElement]:
        raise NotImplementedError("PDF parsing is not part of the SEC HTML MVP")
