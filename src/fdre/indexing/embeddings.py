from __future__ import annotations

import hashlib
import math
import random
import re
import threading
import time
from collections import deque
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal, Protocol

import httpx
from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from apps.api.app.config import Settings
from apps.api.app.models import Chunk, Company, Document, Embedding

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
VOYAGE_MAX_BATCH_SIZE = 128
VOYAGE_DEFAULT_REQUESTS_PER_MINUTE = 2000
VOYAGE_DEFAULT_TOKENS_PER_MINUTE = 3_000_000
RETRYABLE_HTTP_STATUS_CODES = frozenset({429, 502, 503, 504})
EmbeddingInputType = Literal["document", "query"]


def estimate_embedding_tokens(texts: Sequence[str]) -> int:
    return sum(max(1, len(text.split())) for text in texts)


class EmbeddingRateLimiter:
    """Thread-safe sliding-window limiter for provider RPM and TPM caps."""

    def __init__(
        self,
        *,
        requests_per_minute: int | None = None,
        tokens_per_minute: int | None = None,
    ) -> None:
        self._requests_per_minute = requests_per_minute
        self._tokens_per_minute = tokens_per_minute
        self._lock = threading.Lock()
        self._request_times: deque[float] = deque()
        self._token_usage: deque[tuple[float, int]] = deque()

    def acquire(self, *, token_count: int) -> None:
        if self._requests_per_minute is None and self._tokens_per_minute is None:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                cutoff = now - 60.0
                while self._request_times and self._request_times[0] <= cutoff:
                    self._request_times.popleft()
                while self._token_usage and self._token_usage[0][0] <= cutoff:
                    self._token_usage.popleft()

                wait_for = 0.0
                if (
                    self._requests_per_minute is not None
                    and len(self._request_times) >= self._requests_per_minute
                ):
                    wait_for = max(wait_for, self._request_times[0] + 60.0 - now)
                if self._tokens_per_minute is not None and self._token_usage:
                    used_tokens = sum(tokens for _, tokens in self._token_usage)
                    if used_tokens + token_count > self._tokens_per_minute:
                        wait_for = max(wait_for, self._token_usage[0][0] + 60.0 - now)

                if wait_for <= 0:
                    self._request_times.append(now)
                    self._token_usage.append((now, token_count))
                    return
            time.sleep(min(wait_for, 1.0))


def _backoff_seconds(*, attempt: int) -> float:
    backoff = float(2 ** (attempt - 1)) + random.uniform(0.0, 0.5)
    return min(60.0, backoff)


def _retry_after_seconds(response: httpx.Response, *, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return max(float(retry_after), 0.0)
        except ValueError:
            pass
    return _backoff_seconds(attempt=attempt)


def _post_json_with_retries(
    *,
    url: str,
    headers: dict[str, str],
    json_body: dict[str, object],
    timeout: float,
    rate_limiter: EmbeddingRateLimiter | None,
    token_count: int,
    max_attempts: int = 8,
) -> httpx.Response:
    delay_attempt = 1
    for attempt in range(1, max_attempts + 1):
        if rate_limiter is not None:
            rate_limiter.acquire(token_count=token_count)
        try:
            response = httpx.post(url, headers=headers, json=json_body, timeout=timeout)
        except httpx.TransportError:
            # Transient network failures (read timeouts, dropped/reset connections,
            # protocol errors) are common across thousands of requests in a long
            # embedding run; retry them with backoff like retryable status codes
            # rather than letting one blip abort the whole batch.
            if attempt == max_attempts:
                raise
            time.sleep(_backoff_seconds(attempt=delay_attempt))
            delay_attempt += 1
            continue
        if response.status_code not in RETRYABLE_HTTP_STATUS_CODES:
            response.raise_for_status()
            return response
        if attempt == max_attempts:
            response.raise_for_status()
        time.sleep(_retry_after_seconds(response, attempt=delay_attempt))
        delay_attempt += 1
    raise RuntimeError("embedding request retry loop exited unexpectedly")


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int

    def embed_texts(
        self,
        texts: Sequence[str],
        *,
        input_type: EmbeddingInputType = "document",
    ) -> list[list[float]]: ...


class LocalHashEmbeddingProvider:
    name = "local_hash"

    def __init__(self, model: str = "local-hash-v1", dimensions: int = 64) -> None:
        self.model = model
        self.dimensions = dimensions

    def embed_texts(
        self,
        texts: Sequence[str],
        *,
        input_type: EmbeddingInputType = "document",
    ) -> list[list[float]]:
        return [_hash_embedding(text, self.dimensions) for text in texts]


class FakeEmbeddingProvider:
    name = "fake"

    def __init__(self, model: str = "fake-v1", dimensions: int = 8) -> None:
        self.model = model
        self.dimensions = dimensions

    def embed_texts(
        self,
        texts: Sequence[str],
        *,
        input_type: EmbeddingInputType = "document",
    ) -> list[list[float]]:
        return [_hash_embedding(text, self.dimensions) for text in texts]


class OpenAIEmbeddingProvider:
    name = "openai"

    def __init__(self, *, api_key: str, model: str, dimensions: int | None = None) -> None:
        from openai import OpenAI

        self.model = model
        self._client = OpenAI(api_key=api_key)
        default_dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
        }
        self.dimensions = dimensions or default_dimensions.get(model, 0)
        if self.dimensions <= 0:
            raise ValueError("EMBEDDING_DIMENSIONS is required for this OpenAI model")

    def embed_texts(
        self,
        texts: Sequence[str],
        *,
        input_type: EmbeddingInputType = "document",
    ) -> list[list[float]]:
        response = self._client.embeddings.create(
            model=self.model,
            input=list(texts),
            dimensions=self.dimensions,
        )
        vectors = [item.embedding for item in response.data]
        return vectors


class VoyageEmbeddingProvider:
    name = "voyage"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "voyage-4-large",
        dimensions: int = 512,
        api_url: str = "https://api.voyageai.com/v1/embeddings",
        requests_per_minute: int | None = VOYAGE_DEFAULT_REQUESTS_PER_MINUTE,
        tokens_per_minute: int | None = VOYAGE_DEFAULT_TOKENS_PER_MINUTE,
        max_attempts: int = 8,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._api_key = api_key
        self._api_url = api_url
        self._rate_limiter = (
            EmbeddingRateLimiter(
                requests_per_minute=requests_per_minute,
                tokens_per_minute=tokens_per_minute,
            )
            if requests_per_minute is not None or tokens_per_minute is not None
            else None
        )
        self._max_attempts = max_attempts

    def embed_texts(
        self,
        texts: Sequence[str],
        *,
        input_type: EmbeddingInputType = "document",
    ) -> list[list[float]]:
        if len(texts) > VOYAGE_MAX_BATCH_SIZE:
            raise ValueError(
                f"Voyage supports at most {VOYAGE_MAX_BATCH_SIZE} texts per request; "
                f"received {len(texts)}"
            )
        response = _post_json_with_retries(
            url=self._api_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json_body={
                "input": list(texts),
                "model": self.model,
                "input_type": input_type,
                "output_dimension": self.dimensions,
                "output_dtype": "float",
            },
            timeout=60,
            rate_limiter=self._rate_limiter,
            token_count=estimate_embedding_tokens(texts),
            max_attempts=self._max_attempts,
        )
        data = response.json()["data"]
        return [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]


def embedding_provider_from_settings(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "fake":
        return FakeEmbeddingProvider(
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions or 8,
        )
    if settings.embedding_provider == "local_hash":
        return LocalHashEmbeddingProvider(
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions or 64,
        )
    if settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for EMBEDDING_PROVIDER=openai")
        return OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )
    if settings.embedding_provider == "voyage":
        if not settings.voyage_api_key:
            raise ValueError("VOYAGE_API_KEY is required for EMBEDDING_PROVIDER=voyage")
        return VoyageEmbeddingProvider(
            api_key=settings.voyage_api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions or 512,
            requests_per_minute=(
                settings.embedding_requests_per_minute
                if settings.embedding_requests_per_minute is not None
                else VOYAGE_DEFAULT_REQUESTS_PER_MINUTE
            ),
            tokens_per_minute=(
                settings.embedding_tokens_per_minute
                if settings.embedding_tokens_per_minute is not None
                else VOYAGE_DEFAULT_TOKENS_PER_MINUTE
            ),
        )
    raise ValueError(f"Unsupported embedding provider: {settings.embedding_provider}")


def _chunk_select_statement(
    *,
    chunk_ids: list[int] | None,
    document_ids: list[int] | None,
    tickers: list[str] | None,
    missing_only: bool,
    provider: EmbeddingProvider,
) -> Select[tuple[Chunk]]:
    statement = select(Chunk).order_by(Chunk.id)
    if tickers:
        normalized = [ticker.upper() for ticker in tickers]
        statement = (
            statement.join(Chunk.document)
            .join(Document.company)
            .where(Company.ticker.in_(normalized))
        )
    if document_ids is not None:
        statement = statement.where(Chunk.document_id.in_(document_ids))
    if chunk_ids is not None:
        statement = statement.where(Chunk.id.in_(chunk_ids))
    if missing_only:
        matching_embedding = exists().where(
            Embedding.chunk_id == Chunk.id,
            Embedding.provider == provider.name,
            Embedding.model == provider.model,
            Embedding.dimensions == provider.dimensions,
        )
        statement = statement.where(~matching_embedding)
    return statement


def _persist_embedding_batch(
    session: Session,
    provider: EmbeddingProvider,
    batch: list[Chunk],
    vectors: list[list[float]],
) -> int:
    selected_ids = [chunk.id for chunk in batch]
    session.execute(
        delete(Embedding).where(
            Embedding.chunk_id.in_(selected_ids),
            Embedding.provider == provider.name,
            Embedding.model == provider.model,
        )
    )
    for chunk, vector in zip(batch, vectors, strict=True):
        if len(vector) != provider.dimensions:
            raise ValueError(
                f"{provider.name}/{provider.model} returned {len(vector)} dimensions; "
                f"expected {provider.dimensions}"
            )
        session.add(
            Embedding(
                chunk_id=chunk.id,
                provider=provider.name,
                model=provider.model,
                dimensions=len(vector),
                vector=vector,
            )
        )
    session.commit()
    return len(batch)


def rebuild_embeddings(
    session: Session,
    provider: EmbeddingProvider,
    *,
    chunk_ids: list[int] | None = None,
    document_ids: list[int] | None = None,
    tickers: list[str] | None = None,
    missing_only: bool = False,
    batch_size: int = 64,
    concurrency: int = 1,
) -> int:
    statement = _chunk_select_statement(
        chunk_ids=chunk_ids,
        document_ids=document_ids,
        tickers=tickers,
        missing_only=missing_only,
        provider=provider,
    )
    chunks = list(session.scalars(statement))
    if not chunks:
        return 0

    if provider.name == "voyage":
        batch_size = min(batch_size, VOYAGE_MAX_BATCH_SIZE)

    batches = [chunks[offset : offset + batch_size] for offset in range(0, len(chunks), batch_size)]
    workers = max(1, min(concurrency, len(batches)))

    if workers == 1:
        indexed = 0
        for batch in batches:
            vectors = provider.embed_texts(
                [chunk.chunk_text for chunk in batch],
                input_type="document",
            )
            indexed += _persist_embedding_batch(session, provider, batch, vectors)
        return indexed

    indexed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                provider.embed_texts,
                [chunk.chunk_text for chunk in batch],
                input_type="document",
            ): batch
            for batch in batches
        }
        for future in as_completed(futures):
            batch = futures[future]
            vectors = future.result()
            indexed += _persist_embedding_batch(session, provider, batch, vectors)
    return indexed


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _hash_embedding(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    for token in TOKEN_PATTERN.findall(text.casefold()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector
