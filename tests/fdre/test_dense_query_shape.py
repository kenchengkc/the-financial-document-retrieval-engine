from sqlalchemy import select
from sqlalchemy.dialects.postgresql.base import PGDialect

from fdre.retrieval.dense import _exact_accession_candidate_cte
from fdre.retrieval.query import SearchFilters


def _compiled_sql(filters: SearchFilters) -> str:
    candidate_chunks = _exact_accession_candidate_cte(filters)
    statement = select(candidate_chunks.c.chunk_id)
    return " ".join(
        str(
            statement.compile(
                dialect=PGDialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower().split()
    )


def test_exact_accession_candidates_are_materialized_before_vector_search() -> None:
    sql = _compiled_sql(
        SearchFilters(
            tickers=["TSLA", "UAL"],
            accession_numbers=["0000000000-26-000001", "0000000000-26-000002"],
            form_types=["10-Q"],
            amendment_policy="exclude",
            sections=["Risk Factors"],
        )
    )

    assert "as materialized" in sql
    assert "join documents" in sql
    assert "join companies" in sql
    assert "documents.accession_number in" in sql
    assert "chunks.section in" in sql
    assert "embeddings" not in sql


def test_exact_accession_candidates_skip_company_join_without_company_filters() -> None:
    sql = _compiled_sql(
        SearchFilters(accession_numbers=["0000000000-26-000001"])
    )

    assert "as materialized" in sql
    assert "join documents" in sql
    assert "join companies" not in sql
