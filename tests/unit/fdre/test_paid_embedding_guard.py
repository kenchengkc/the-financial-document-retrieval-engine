from __future__ import annotations

from argparse import Namespace

import pytest
import respx
import scripts.ingestion.ingest_ticker_batch as ingest_ticker_batch
from httpx import Response

from apps.api.app.config import Settings
from fdre.indexing.embeddings import VoyageEmbeddingProvider, embedding_provider_from_settings


def voyage_settings(*, enabled: bool, price: float = 0.12) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]  # Supported by BaseSettings at runtime.
        EMBEDDING_PROVIDER="voyage",
        EMBEDDING_MODEL="voyage-4-large",
        EMBEDDING_DIMENSIONS=2,
        VOYAGE_API_KEY="test-key",
        PAID_EMBEDDING_INDEXING_ENABLED=enabled,
        EMBEDDING_COST_PER_MILLION_TOKENS=price,
    )


@respx.mock
def test_paid_document_embedding_is_disabled_by_default_before_any_request() -> None:
    provider = VoyageEmbeddingProvider(api_key="test-key", dimensions=2)

    with pytest.raises(RuntimeError, match="Paid document embedding is disabled"):
        provider.embed_texts(["New filing text"])


@respx.mock
def test_settings_block_paid_document_embedding_without_opt_in() -> None:
    provider = embedding_provider_from_settings(voyage_settings(enabled=False))

    with pytest.raises(RuntimeError, match="Paid document embedding is disabled"):
        provider.embed_texts(["New filing text"])


@respx.mock
def test_blocking_background_indexing_preserves_query_embeddings() -> None:
    route = respx.post("https://api.voyageai.com/v1/embeddings").mock(
        return_value=Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})
    )
    provider = embedding_provider_from_settings(voyage_settings(enabled=False))

    assert provider.embed_texts(["Data center construction"], input_type="query") == [[1.0, 0.0]]
    assert route.call_count == 1


@respx.mock
def test_explicit_opt_in_enables_paid_document_embedding_and_separates_cached_providers() -> None:
    route = respx.post("https://api.voyageai.com/v1/embeddings").mock(
        return_value=Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})
    )
    disabled = embedding_provider_from_settings(voyage_settings(enabled=False))
    enabled = embedding_provider_from_settings(voyage_settings(enabled=True))

    assert disabled is not enabled
    assert enabled.embed_texts(["New filing text"]) == [[1.0, 0.0]]
    with pytest.raises(RuntimeError, match="Paid document embedding is disabled"):
        disabled.embed_texts(["New filing text"])
    assert route.call_count == 1


def test_paid_indexing_requires_a_price_for_cost_reports() -> None:
    with pytest.raises(ValueError, match="EMBEDDING_COST_PER_MILLION_TOKENS"):
        embedding_provider_from_settings(voyage_settings(enabled=True, price=0))


def test_local_document_embeddings_remain_available_without_opt_in() -> None:
    provider = embedding_provider_from_settings(Settings(EMBEDDING_PROVIDER="local_hash"))

    assert len(provider.embed_texts(["New filing text"])[0]) == provider.dimensions


@pytest.mark.parametrize("provider_name", ["voyage", "openai"])
def test_unapproved_paid_ingestion_stops_before_database_changes(
    monkeypatch: pytest.MonkeyPatch, provider_name: str
) -> None:
    monkeypatch.setattr(ingest_ticker_batch, "parse_args", lambda: Namespace(tickers=["AAPL"]))
    monkeypatch.setattr(
        ingest_ticker_batch,
        "get_settings",
        lambda: Settings(EMBEDDING_PROVIDER=provider_name, PAID_EMBEDDING_INDEXING_ENABLED=False),
    )

    def database_must_not_be_opened() -> None:
        pytest.fail("Unapproved paid indexing must stop before opening the database")

    monkeypatch.setattr(ingest_ticker_batch, "create_db_engine", database_must_not_be_opened)

    with pytest.raises(RuntimeError, match="Paid document embedding is disabled"):
        ingest_ticker_batch.main()
