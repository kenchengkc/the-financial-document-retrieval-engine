from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.db import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Historical-only SEC issuers do not necessarily have a current tradable ticker. Keeping
    # ticker nullable prevents us from inventing a present-day identifier merely to satisfy the
    # issuer foreign-key used by the stable security master.
    ticker: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    cik: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(64))
    sector: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    documents: Mapped[list[Document]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    financial_facts: Mapped[list[FinancialFact]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )


from apps.api.app.models.documents import Document  # noqa: E402
from apps.api.app.models.financial_facts import FinancialFact  # noqa: E402
