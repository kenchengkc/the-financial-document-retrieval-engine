from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.db import Base

JSONDict = dict[str, Any]


class FinancialFact(Base):
    __tablename__ = "financial_facts"
    __table_args__ = (
        UniqueConstraint("fact_key", name="uq_financial_facts_fact_key"),
        Index(
            "ix_financial_facts_ticker_metric_period",
            "ticker",
            "canonical_metric",
            "period_end",
        ),
        Index(
            "ix_financial_facts_document_metric",
            "document_id",
            "canonical_metric",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    ticker: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    fact_key: Mapped[str | None] = mapped_column(String(64))
    taxonomy: Mapped[str | None] = mapped_column(String(64))
    concept: Mapped[str] = mapped_column(String(256), index=True, nullable=False)
    canonical_metric: Mapped[str | None] = mapped_column(String(64), index=True)
    label: Mapped[str | None] = mapped_column(Text)
    value: Mapped[Decimal | None] = mapped_column(Numeric(precision=24, scale=6))
    unit: Mapped[str | None] = mapped_column(String(64))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date, index=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, index=True)
    fiscal_period: Mapped[str | None] = mapped_column(String(16))
    period_type: Mapped[str | None] = mapped_column(String(16))
    frame: Mapped[str | None] = mapped_column(String(32))
    form_type: Mapped[str | None] = mapped_column(String(32), index=True)
    accession_number: Mapped[str | None] = mapped_column(String(64), index=True)
    filed_at: Mapped[date | None] = mapped_column(Date)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    is_amendment: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    is_restatement: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[JSONDict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    company: Mapped[Company] = relationship(back_populates="financial_facts")
    document: Mapped[Document | None] = relationship()


from apps.api.app.models.companies import Company  # noqa: E402
from apps.api.app.models.documents import Document  # noqa: E402
