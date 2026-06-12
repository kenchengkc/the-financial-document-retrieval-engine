from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.db import Base

JSONDict = dict[str, Any]


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_key: Mapped[str] = mapped_column(String(64), index=True, unique=True, nullable=False)
    pipeline: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    config_json: Mapped[JSONDict] = mapped_column(JSON, nullable=False)
    stage_counts_json: Mapped[JSONDict] = mapped_column(JSON, nullable=False)
    failures_json: Mapped[list[JSONDict]] = mapped_column(JSON, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    provider_usage_json: Mapped[JSONDict] = mapped_column(JSON, nullable=False)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=8),
        default=Decimal(0),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
