from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.db import Base

JSONDict = dict[str, Any]


class ResearchExperiment(Base):
    __tablename__ = "research_experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_key: Mapped[str] = mapped_column(
        String(64),
        index=True,
        unique=True,
        nullable=False,
    )
    experiment_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    feature_version: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    code_sha: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    config_json: Mapped[JSONDict] = mapped_column(JSON, nullable=False)
    results_json: Mapped[JSONDict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
