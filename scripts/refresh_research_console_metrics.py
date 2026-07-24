from __future__ import annotations

from sqlalchemy.orm import Session

from apps.api.app.db import get_engine
from apps.api.app.services.operations_service import refresh_research_console_snapshots


def main() -> None:
    with Session(get_engine()) as session:
        report = refresh_research_console_snapshots(session)
    print(
        {
            "status": "completed",
            "generated_at": report.generated_at.isoformat(),
            "companies": report.company_count,
            "documents": report.document_count,
            "chunks": report.chunk_count,
        }
    )


if __name__ == "__main__":
    main()
