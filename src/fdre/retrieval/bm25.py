"""A small, dependency-free BM25 Okapi ranker.

Postgres full-text search (``ts_rank_cd``) is a fast, indexed candidate
generator but ranks by cover density, not BM25's saturating TF-IDF. We re-rank
the lexical candidate pool with BM25 Okapi — document frequencies are taken over
the pool, which is the standard approach for BM25 re-ranking of a retrieved set.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class BM25Okapi:
    def __init__(
        self,
        corpus_tokens: Sequence[Sequence[str]],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.k1 = k1
        self.b = b
        self._doc_freqs = [Counter(doc) for doc in corpus_tokens]
        self._doc_len = [len(doc) for doc in corpus_tokens]
        self._n = len(corpus_tokens)
        self._avgdl = (sum(self._doc_len) / self._n) if self._n else 0.0
        document_frequency: Counter[str] = Counter()
        for doc in corpus_tokens:
            document_frequency.update(set(doc))
        self._idf = {
            term: math.log((self._n - freq + 0.5) / (freq + 0.5) + 1.0)
            for term, freq in document_frequency.items()
        }

    def scores(self, query_tokens: Sequence[str]) -> list[float]:
        if self._n == 0 or self._avgdl == 0.0:
            return [0.0] * self._n
        query_terms = [term for term in query_tokens if term in self._idf]
        results: list[float] = []
        for index in range(self._n):
            term_freqs = self._doc_freqs[index]
            length = self._doc_len[index]
            score = 0.0
            for term in query_terms:
                freq = term_freqs.get(term, 0)
                if freq == 0:
                    continue
                denominator = freq + self.k1 * (1 - self.b + self.b * length / self._avgdl)
                score += self._idf[term] * (freq * (self.k1 + 1)) / denominator
            results.append(score)
        return results


def bm25_rank(
    query: str, documents: Sequence[str], *, k1: float = 1.5, b: float = 0.75
) -> list[int]:
    """Return document indices ordered by descending BM25 score (stable)."""
    model = BM25Okapi([tokenize(doc) for doc in documents], k1=k1, b=b)
    scored = list(enumerate(model.scores(tokenize(query))))
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return [index for index, _ in scored]
