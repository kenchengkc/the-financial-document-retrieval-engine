from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.app.config import Settings
from apps.api.app.models import Chunk, Embedding

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...


class LocalHashEmbeddingProvider:
    name = "local_hash"

    def __init__(self, model: str = "local-hash-v1", dimensions: int = 64) -> None:
        self.model = model
        self.dimensions = dimensions

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [_hash_embedding(text, self.dimensions) for text in texts]


class FakeEmbeddingProvider:
    name = "fake"

    def __init__(self, model: str = "fake-v1", dimensions: int = 8) -> None:
        self.model = model
        self.dimensions = dimensions

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [_hash_embedding(text, self.dimensions) for text in texts]


class OpenAIEmbeddingProvider:
    name = "openai"

    def __init__(self, *, api_key: str, model: str) -> None:
        from openai import OpenAI

        self.model = model
        self._client = OpenAI(api_key=api_key)
        self.dimensions = 0

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self.model, input=list(texts))
        vectors = [item.embedding for item in response.data]
        if vectors:
            self.dimensions = len(vectors[0])
        return vectors


def embedding_provider_from_settings(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "fake":
        return FakeEmbeddingProvider(model=settings.embedding_model)
    if settings.embedding_provider == "local_hash":
        return LocalHashEmbeddingProvider(model=settings.embedding_model)
    if settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for EMBEDDING_PROVIDER=openai")
        return OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key,
            model=settings.embedding_model,
        )
    raise ValueError(f"Unsupported embedding provider: {settings.embedding_provider}")


def rebuild_embeddings(
    session: Session,
    provider: EmbeddingProvider,
    *,
    chunk_ids: list[int] | None = None,
    missing_only: bool = False,
) -> int:
    statement = select(Chunk).order_by(Chunk.id)
    if chunk_ids is not None:
        statement = statement.where(Chunk.id.in_(chunk_ids))
    if missing_only:
        existing_chunk_ids = select(Embedding.chunk_id).where(
            Embedding.provider == provider.name,
            Embedding.model == provider.model,
        )
        statement = statement.where(~Chunk.id.in_(existing_chunk_ids))
    chunks = list(session.scalars(statement))
    if not chunks:
        return 0

    selected_ids = [chunk.id for chunk in chunks]
    if not missing_only:
        session.execute(
            delete(Embedding).where(
                Embedding.chunk_id.in_(selected_ids),
                Embedding.provider == provider.name,
                Embedding.model == provider.model,
            )
        )
    vectors = provider.embed_texts([chunk.chunk_text for chunk in chunks])
    for chunk, vector in zip(chunks, vectors, strict=True):
        session.add(
            Embedding(
                chunk_id=chunk.id,
                provider=provider.name,
                model=provider.model,
                dimensions=len(vector),
                vector_json=vector,
            )
        )
    session.commit()
    return len(chunks)


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
