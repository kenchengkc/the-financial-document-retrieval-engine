from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import Document, DocumentElement

ChangeType = Literal["added", "removed", "materially_changed"]


class PassageChange(BaseModel):
    change_type: ChangeType
    section: str
    before_text: str | None = None
    after_text: str | None = None
    before_fingerprint: str | None = None
    after_fingerprint: str | None = None
    similarity: float | None = Field(default=None, ge=0.0, le=1.0)


class FilingDifference(BaseModel):
    company_ticker: str
    current_accession: str
    previous_accession: str
    current_available_at: datetime | None
    previous_available_at: datetime | None
    comparison_basis: str
    changes: list[PassageChange]
    added_count: int
    removed_count: int
    materially_changed_count: int


def compare_filing_to_prior(
    session: Session,
    accession_number: str,
    *,
    as_of: datetime | None = None,
) -> FilingDifference:
    current = session.scalar(
        select(Document).where(Document.accession_number == accession_number)
    )
    if current is None:
        raise ValueError(f"Filing {accession_number} does not exist")
    if as_of is not None and (
        current.available_at is None or current.available_at > as_of
    ):
        raise ValueError(f"Filing {accession_number} was not public as of {as_of.isoformat()}")
    previous, basis = select_comparable_document(session, current, as_of=as_of)
    if previous is None:
        raise ValueError(f"No comparable filing exists for {accession_number}")
    return diff_documents(session, previous, current, comparison_basis=basis)


def select_comparable_document(
    session: Session,
    current: Document,
    *,
    as_of: datetime | None = None,
) -> tuple[Document | None, str]:
    candidates = list(
        session.scalars(
            select(Document).where(Document.company_id == current.company_id)
        )
    )
    return select_comparable_document_from_candidates(
        current,
        candidates,
        as_of=as_of,
    )


def select_comparable_document_from_candidates(
    current: Document,
    documents: Sequence[Document],
    *,
    as_of: datetime | None = None,
) -> tuple[Document | None, str]:
    if current.is_amendment and current.amends_accession_number:
        original = next(
            (
                document
                for document in documents
                if document.accession_number == current.amends_accession_number
            ),
            None,
        )
        if original is not None and (
            as_of is None
            or (original.available_at is not None and original.available_at <= as_of)
        ):
            return original, "amendment_to_original"

    base_form = current.form_type.upper().removesuffix("/A")
    candidates = [
        document
        for document in documents
        if current.period_end_date is not None
        and document.company_id == current.company_id
        and document.id != current.id
        and not document.is_amendment
        and document.period_end_date is not None
        and document.period_end_date < current.period_end_date
        and document.form_type.upper().removesuffix("/A") == base_form
        and (
            as_of is None
            or (document.available_at is not None and document.available_at <= as_of)
        )
    ]
    if not candidates:
        return None, "none"

    if base_form == "10-Q" and current.period_end_date is not None:
        target = current.period_end_date - timedelta(days=365)
        return (
            min(
                candidates,
                key=lambda document: (
                    abs((document.period_end_date - target).days)
                    if document.period_end_date
                    else 100_000,
                    -(document.period_end_date.toordinal() if document.period_end_date else 0),
                    document.id,
                ),
            ),
            "same_quarter_prior_year",
        )
    return (
        max(
            candidates,
            key=lambda document: (
                document.period_end_date or datetime.min.date(),
                document.available_at.timestamp() if document.available_at else float("-inf"),
                document.id,
            ),
        ),
        "prior_annual_period" if base_form == "10-K" else "prior_period",
    )


def diff_documents(
    session: Session,
    previous: Document,
    current: Document,
    *,
    comparison_basis: str,
) -> FilingDifference:
    previous_sections = _passages_by_section(session, previous.id)
    current_sections = _passages_by_section(session, current.id)
    changes: list[PassageChange] = []
    for section in sorted(previous_sections.keys() | current_sections.keys()):
        changes.extend(
            _diff_section(
                section,
                previous_sections.get(section, []),
                current_sections.get(section, []),
            )
        )
    counts = {
        change_type: sum(change.change_type == change_type for change in changes)
        for change_type in ("added", "removed", "materially_changed")
    }
    return FilingDifference(
        company_ticker=current.company.ticker,
        current_accession=current.accession_number,
        previous_accession=previous.accession_number,
        current_available_at=current.available_at,
        previous_available_at=previous.available_at,
        comparison_basis=comparison_basis,
        changes=changes,
        added_count=counts["added"],
        removed_count=counts["removed"],
        materially_changed_count=counts["materially_changed"],
    )


def _passages_by_section(session: Session, document_id: int) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = defaultdict(list)
    elements = session.scalars(
        select(DocumentElement)
        .where(DocumentElement.document_id == document_id)
        .order_by(DocumentElement.reading_order, DocumentElement.id)
    )
    for element in elements:
        text = (element.markdown if element.element_type == "table" else element.text) or ""
        normalized = _normalize_passage(text)
        if normalized:
            sections[element.section or "Unsectioned"].append(normalized)
    return dict(sections)


def _diff_section(
    section: str,
    before: list[str],
    after: list[str],
) -> list[PassageChange]:
    matcher = SequenceMatcher(a=before, b=after, autojunk=False)
    changes: list[PassageChange] = []
    for operation, before_start, before_end, after_start, after_end in matcher.get_opcodes():
        if operation == "equal":
            continue
        before_passages = before[before_start:before_end]
        after_passages = after[after_start:after_end]
        if operation == "replace":
            paired = min(len(before_passages), len(after_passages))
            for index in range(paired):
                old = before_passages[index]
                new = after_passages[index]
                changes.append(
                    PassageChange(
                        change_type="materially_changed",
                        section=section,
                        before_text=old,
                        after_text=new,
                        before_fingerprint=_fingerprint(old),
                        after_fingerprint=_fingerprint(new),
                        similarity=SequenceMatcher(a=old, b=new, autojunk=False).ratio(),
                    )
                )
            before_passages = before_passages[paired:]
            after_passages = after_passages[paired:]
        changes.extend(
            PassageChange(
                change_type="removed",
                section=section,
                before_text=passage,
                before_fingerprint=_fingerprint(passage),
            )
            for passage in before_passages
        )
        changes.extend(
            PassageChange(
                change_type="added",
                section=section,
                after_text=passage,
                after_fingerprint=_fingerprint(passage),
            )
            for passage in after_passages
        )
    return changes


def _normalize_passage(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _fingerprint(value: str) -> str:
    normalized = _normalize_passage(value).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
