from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from fdre.retrieval.query import RetrievalCandidate

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")


class AnswerClaim(BaseModel):
    claim_text: str
    citation_chunk_ids: list[int] = Field(default_factory=list)
    citation_text: str | None = None


class VerifiedCitation(BaseModel):
    chunk_id: int
    claim_text: str
    citation_text: str
    metadata: dict[str, Any]
    confidence: float


class CitationVerification(BaseModel):
    valid: bool
    citations: list[VerifiedCitation] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class CitationVerifier:
    def verify(
        self,
        claims: list[AnswerClaim],
        evidence: list[RetrievalCandidate],
    ) -> CitationVerification:
        evidence_by_id = {candidate.chunk_id: candidate for candidate in evidence}
        citations: list[VerifiedCitation] = []
        errors: list[str] = []
        for claim in claims:
            if not claim.citation_chunk_ids:
                errors.append(f"Claim has no citation: {claim.claim_text}")
                continue
            for chunk_id in claim.citation_chunk_ids:
                candidate = evidence_by_id.get(chunk_id)
                if candidate is None:
                    errors.append(f"Citation chunk {chunk_id} was not retrieved")
                    continue
                citation_text = claim.citation_text or candidate.text
                overlap = _token_overlap(citation_text, candidate.text)
                if overlap < 0.6:
                    errors.append(f"Citation text does not match chunk {chunk_id}")
                    continue
                citations.append(
                    VerifiedCitation(
                        chunk_id=chunk_id,
                        claim_text=claim.claim_text,
                        citation_text=citation_text,
                        metadata=candidate.metadata,
                        confidence=overlap,
                    )
                )
        return CitationVerification(
            valid=bool(claims) and not errors,
            citations=citations,
            errors=errors,
        )


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(TOKEN_PATTERN.findall(left.casefold()))
    right_tokens = set(TOKEN_PATTERN.findall(right.casefold()))
    if not left_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)
