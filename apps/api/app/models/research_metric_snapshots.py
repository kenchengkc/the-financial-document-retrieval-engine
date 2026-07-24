from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.db import Base


class ResearchMetricSnapshot(Base):
    """Materialized Research Console metrics refreshed after corpus changes."""

    __tablename__ = "research_metric_snapshots"

    metric_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
