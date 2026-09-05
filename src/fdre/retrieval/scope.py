from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.sql import ColumnElement

from apps.api.app.models import Document

RESEARCH_ARCHIVE_PROFILE = "fdre-research-archive-v1"


def document_is_retrieval_indexable(document: Any) -> bool:
    """Return False for documents materialized only for the bounded research archive."""

    metadata = getattr(document, "metadata_json", None) or {}
    archive_metadata = metadata.get("research_archive")
    return not (
        isinstance(archive_metadata, dict)
        and archive_metadata.get("profile") == RESEARCH_ARCHIVE_PROFILE
    )


def retrieval_indexable_document_clause() -> ColumnElement[bool]:
    """SQL predicate excluding research-archive-only documents from live retrieval."""

    archive_profile = Document.metadata_json["research_archive"]["profile"].as_string()
    return or_(
        Document.metadata_json.is_(None),
        archive_profile.is_(None),
        archive_profile != RESEARCH_ARCHIVE_PROFILE,
    )
