from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

ElementType = Literal["text", "table", "figure", "title", "section_header"]


class ParsedElement(BaseModel):
    element_type: ElementType
    text: str | None = None
    markdown: str | None = None
    page_number: int | None = None
    section: str | None = None
    bbox: dict[str, float] | None = None
    reading_order: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseDocumentParser(ABC):
    @abstractmethod
    def parse(self, content: str | bytes) -> list[ParsedElement]:
        """Parse a document into ordered retrieval elements."""

    def parse_file(self, path: str | Path) -> list[ParsedElement]:
        return self.parse(Path(path).read_bytes())
