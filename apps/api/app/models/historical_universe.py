from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.db import Base


class Security(Base):
    """Stable listed-security identity beneath an SEC issuer/company."""

    __tablename__ = "securities"
    __table_args__ = (
        Index("ix_securities_company_type", "company_id", "security_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    security_type: Mapped[str] = mapped_column(
        String(32),
        default="common_stock",
        server_default="common_stock",
        nullable=False,
    )
    share_class: Mapped[str | None] = mapped_column(String(64))
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

    identity_periods: Mapped[list[SecurityIdentityPeriod]] = relationship(
        back_populates="security",
        cascade="all, delete-orphan",
    )
    universe_memberships: Mapped[list[UniverseMembership]] = relationship(
        back_populates="security",
        cascade="all, delete-orphan",
    )


class SecurityIdentityPeriod(Base):
    """Ticker/name/exchange identity valid over a half-open effective interval."""

    __tablename__ = "security_identity_periods"
    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "symbol",
            "effective_from",
            name="uq_security_identity_period_start",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_security_identity_period_valid_range",
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_security_identity_period_confidence",
        ),
        CheckConstraint(
            "verification_status IN ('verified', 'provisional', 'rejected')",
            name="ck_security_identity_period_verification_status",
        ),
        Index(
            "ix_security_identity_symbol_effective",
            "symbol",
            "effective_from",
            "effective_to",
        ),
        Index(
            "ix_security_identity_security_effective",
            "security_id",
            "effective_from",
            "effective_to",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    exchange: Mapped[str | None] = mapped_column(String(64))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(16),
        default="provisional",
        server_default="provisional",
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        default=1.0,
        server_default="1.0",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    security: Mapped[Security] = relationship(back_populates="identity_periods")


class UniverseMembership(Base):
    """Security membership in a named research universe over a half-open interval."""

    __tablename__ = "universe_memberships"
    __table_args__ = (
        UniqueConstraint(
            "universe_code",
            "security_id",
            "effective_from",
            name="uq_universe_membership_period_start",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_universe_membership_valid_range",
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_universe_membership_confidence",
        ),
        CheckConstraint(
            "verification_status IN ('verified', 'provisional', 'rejected')",
            name="ck_universe_membership_verification_status",
        ),
        Index(
            "ix_universe_membership_universe_effective",
            "universe_code",
            "effective_from",
            "effective_to",
        ),
        Index(
            "ix_universe_membership_security_effective",
            "security_id",
            "effective_from",
            "effective_to",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    universe_code: Mapped[str] = mapped_column(String(32), nullable=False)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"),
        nullable=False,
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    announced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(16),
        default="provisional",
        server_default="provisional",
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        default=1.0,
        server_default="1.0",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    security: Mapped[Security] = relationship(back_populates="universe_memberships")
