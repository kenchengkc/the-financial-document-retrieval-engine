from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.db import Base

JSONDict = dict[str, Any]


class FinancialFact(Base):
    __tablename__ = "financial_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    ticker: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    concept: Mapped[str] = mapped_column(String(256), index=True, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    value: Mapped[Decimal | None] = mapped_column(Numeric(precision=24, scale=6))
    unit: Mapped[str | None] = mapped_column(String(64))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date, index=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, index=True)
    fiscal_period: Mapped[str | None] = mapped_column(String(16))
    form_type: Mapped[str | None] = mapped_column(String(32), index=True)
    accession_number: Mapped[str | None] = mapped_column(String(64), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[JSONDict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    company: Mapped[Company] = relationship(back_populates="financial_facts")


from apps.api.app.models.companies import Company  # noqa: E402
