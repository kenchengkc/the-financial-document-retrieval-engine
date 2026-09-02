from __future__ import annotations

from typing import Any

from apps.api.app.models import DocumentElement
from fdre.chunking.element_chunker import ChunkSpec


class TableChunker:
    """Preserve table structure and add a compact retrieval-oriented summary."""

    def chunk(
        self,
        element: DocumentElement,
        *,
        metadata: dict[str, Any],
    ) -> list[ChunkSpec]:
        markdown = (element.markdown or "").strip()
        if not markdown:
            return []

        payload = element.json_payload or {}
        headers = _string_list(payload.get("headers"))
        row_count = _integer(payload.get("row_count"))
        column_count = _integer(payload.get("column_count"))
        table_metadata = {
            **metadata,
            "row_count": row_count,
            "column_count": column_count,
            "headers": headers,
        }
        summary = _table_summary(
            section=element.section,
            headers=headers,
            row_count=row_count,
            column_count=column_count,
        )
        return [
            ChunkSpec(
                chunk_text=markdown,
                chunk_type="table_markdown",
                section=element.section,
                page_start=element.page_number,
                page_end=element.page_number,
                token_count=len(markdown.split()),
                metadata=table_metadata,
            ),
            ChunkSpec(
                chunk_text=summary,
                chunk_type="table_summary",
                section=element.section,
                page_start=element.page_number,
                page_end=element.page_number,
                token_count=len(summary.split()),
                metadata=table_metadata,
            ),
        ]


def _table_summary(
    *,
    section: str | None,
    headers: list[str],
    row_count: int | None,
    column_count: int | None,
) -> str:
    location = f" in the {section} section" if section else ""
    dimensions = []
    if row_count is not None:
        dimensions.append(f"{row_count} data rows")
    if column_count is not None:
        dimensions.append(f"{column_count} columns")
    dimension_text = f" with {' and '.join(dimensions)}" if dimensions else ""
    header_text = f". Columns: {', '.join(headers)}" if headers else ""
    return f"Financial table{location}{dimension_text}{header_text}."


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) else None
