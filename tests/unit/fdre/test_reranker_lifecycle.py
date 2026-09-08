from apps.api.app.config import Settings
from fdre.retrieval.rerank import reranker_from_settings


def test_reranker_factory_reuses_instance_for_same_configuration() -> None:
    first = reranker_from_settings(Settings(RERANKER_PROVIDER="fake"))
    second = reranker_from_settings(Settings(RERANKER_PROVIDER="fake"))

    assert first is second


def test_reranker_factory_separates_distinct_configurations() -> None:
    fake = reranker_from_settings(Settings(RERANKER_PROVIDER="fake"))
    disabled = reranker_from_settings(Settings(RERANKER_PROVIDER="none"))

    assert fake is not disabled


def test_voyage_reranker_cache_is_scoped_by_credentials_and_model() -> None:
    first = reranker_from_settings(
        Settings(
            RERANKER_PROVIDER="voyage",
            RERANKER_MODEL="rerank-2.5",
            VOYAGE_API_KEY="test-key-a",
        )
    )
    same = reranker_from_settings(
        Settings(
            RERANKER_PROVIDER="voyage",
            RERANKER_MODEL="rerank-2.5",
            VOYAGE_API_KEY="test-key-a",
        )
    )
    different_key = reranker_from_settings(
        Settings(
            RERANKER_PROVIDER="voyage",
            RERANKER_MODEL="rerank-2.5",
            VOYAGE_API_KEY="test-key-b",
        )
    )

    assert first is same
    assert first is not different_key
