from __future__ import annotations

import hashlib
import math
import random
import re
import time
from collections.abc import Sequence
from typing import Literal, Protocol

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.app.config import Settings
from apps.api.app.models import Chunk, Embedding

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
VOYAGE_MAX_BATCH_SIZE = 128
RETRYABLE_HTTP_STATUS_CODES = frozenset({429, 502, 503, 504})
EmbeddingInputType = Literal["document", "query"]


class RequestPacer:
    """Pace outbound embedding requests to stay under provider RPM limits."""

    def __init__(self, requests_per_minute: int) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        self._minimum_interval = 60.0 / requests_per_minute
        self._last_request_at: float | None = None

    def wait(self) -> None:
        now = time.monotonic()
        if self._last_request_at is not None:
            remaining = self._minimum_interval - (now - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
                now = time.monotonic()
        self._last_request_at = now


def _retry_after_seconds(response: httpx.Response, *, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return max(float(retry_after), 0.0)
        except ValueError:
            pass
    backoff = float(2 ** (attempt - 1)) + random.uniform(0.0, 0.5)
    return min(60.0, backoff)


def _post_json_with_retries(
    *,
    url: str,
    headers: dict[str, str],
    json_body: dict[str, object],
    timeout: float,
    pacer: RequestPacer | None,
    max_attempts: int = 8,
) -> httpx.Response:
    delay_attempt = 1
    for attempt in range(1, max_attempts + 1):
        if pacer is not None:
            pacer.wait()
        response = httpx.post(url, headers=headers, json=json_body, timeout=timeout)
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
        requests_per_minute: int | None = 2,
        max_attempts: int = 8,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._api_key = api_key
        self._api_url = api_url
        self._pacer = (
            RequestPacer(requests_per_minute) if requests_per_minute is not None else None
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
            pacer=self._pacer,
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
        requests_per_minute = settings.embedding_requests_per_minute
        if requests_per_minute is None:
            requests_per_minute = 2
        return VoyageEmbeddingProvider(
            api_key=settings.voyage_api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions or 512,
            requests_per_minute=requests_per_minute,
        )
    raise ValueError(f"Unsupported embedding provider: {settings.embedding_provider}")


def rebuild_embeddings(
    session: Session,
    provider: EmbeddingProvider,
    *,
    chunk_ids: list[int] | None = None,
    missing_only: bool = False,
    batch_size: int = 64,
) -> int:
    statement = select(Chunk).order_by(Chunk.id)
    if chunk_ids is not None:
        statement = statement.where(Chunk.id.in_(chunk_ids))
    if missing_only:
        existing_chunk_ids = select(Embedding.chunk_id).where(
            Embedding.provider == provider.name,
            Embedding.model == provider.model,
            Embedding.dimensions == provider.dimensions,
        )
        statement = statement.where(~Chunk.id.in_(existing_chunk_ids))
    chunks = list(session.scalars(statement))
    if not chunks:
        return 0

    if provider.name == "voyage":
        batch_size = min(batch_size, VOYAGE_MAX_BATCH_SIZE)

    indexed = 0
    for offset in range(0, len(chunks), batch_size):
        batch = chunks[offset : offset + batch_size]
        selected_ids = [chunk.id for chunk in batch]
        vectors = provider.embed_texts(
            [chunk.chunk_text for chunk in batch],
            input_type="document",
        )
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
        indexed += len(batch)
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
