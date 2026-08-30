import pytest

from apps.api.app.config import normalize_database_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        (
            "postgresql://user:pass@example.test/fdre",
            "postgresql+psycopg://user:pass@example.test/fdre",
        ),
        (
            "postgres://user:pass@example.test/fdre",
            "postgresql+psycopg://user:pass@example.test/fdre",
        ),
        (
            "postgresql+psycopg://user:pass@example.test/fdre",
            "postgresql+psycopg://user:pass@example.test/fdre",
        ),
        (
            "sqlite+pysqlite:///:memory:",
            "sqlite+pysqlite:///:memory:",
        ),
    ),
)
def test_normalize_database_url(raw: str, expected: str) -> None:
    assert normalize_database_url(raw) == expected
