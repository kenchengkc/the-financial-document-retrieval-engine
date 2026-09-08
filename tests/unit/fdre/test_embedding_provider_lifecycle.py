from apps.api.app.config import Settings
from fdre.indexing.embeddings import (
    _shared_http_client,
    embedding_provider_from_settings,
)


def test_embedding_provider_factory_reuses_same_configuration() -> None:
    first = embedding_provider_from_settings(
        Settings(
            EMBEDDING_PROVIDER="local_hash",
            EMBEDDING_MODEL="local-hash-v1",
            EMBEDDING_DIMENSIONS=64,
        )
    )
    second = embedding_provider_from_settings(
        Settings(
            EMBEDDING_PROVIDER="local_hash",
            EMBEDDING_MODEL="local-hash-v1",
            EMBEDDING_DIMENSIONS=64,
        )
    )

    assert first is second


def test_embedding_provider_factory_separates_distinct_dimensions() -> None:
    smaller = embedding_provider_from_settings(
        Settings(
            EMBEDDING_PROVIDER="local_hash",
            EMBEDDING_MODEL="local-hash-v1",
            EMBEDDING_DIMENSIONS=64,
        )
    )
    larger = embedding_provider_from_settings(
        Settings(
            EMBEDDING_PROVIDER="local_hash",
            EMBEDDING_MODEL="local-hash-v1",
            EMBEDDING_DIMENSIONS=128,
        )
    )

    assert smaller is not larger


def test_voyage_embedding_cache_is_scoped_by_credentials_and_limits() -> None:
    first = embedding_provider_from_settings(
        Settings(
            EMBEDDING_PROVIDER="voyage",
            EMBEDDING_MODEL="voyage-4-large",
            EMBEDDING_DIMENSIONS=512,
            EMBEDDING_REQUESTS_PER_MINUTE=100,
            EMBEDDING_TOKENS_PER_MINUTE=10000,
            VOYAGE_API_KEY="test-key-a",
        )
    )
    same = embedding_provider_from_settings(
        Settings(
            EMBEDDING_PROVIDER="voyage",
            EMBEDDING_MODEL="voyage-4-large",
            EMBEDDING_DIMENSIONS=512,
            EMBEDDING_REQUESTS_PER_MINUTE=100,
            EMBEDDING_TOKENS_PER_MINUTE=10000,
            VOYAGE_API_KEY="test-key-a",
        )
    )
    different_key = embedding_provider_from_settings(
        Settings(
            EMBEDDING_PROVIDER="voyage",
            EMBEDDING_MODEL="voyage-4-large",
            EMBEDDING_DIMENSIONS=512,
            EMBEDDING_REQUESTS_PER_MINUTE=100,
            EMBEDDING_TOKENS_PER_MINUTE=10000,
            VOYAGE_API_KEY="test-key-b",
        )
    )

    assert first is same
    assert first is not different_key


def test_shared_http_client_reuses_pool_for_same_timeout() -> None:
    assert _shared_http_client(60.0) is _shared_http_client(60.0)
    assert _shared_http_client(30.0) is not _shared_http_client(60.0)
