from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.db import Base


class OperationReceipt(Base):
    """Durable receipt committed atomically with a state-changing operation."""

    __tablename__ = "operation_receipts"
    __table_args__ = (
        Index("ix_operation_receipts_type_created", "operation_type", "created_at"),
    )

    operation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
