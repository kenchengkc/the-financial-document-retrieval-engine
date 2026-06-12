from fdre.research.thematic import diversify_candidates_by_issuer
from fdre.retrieval.query import RetrievalCandidate


def _candidate(chunk_id: int, ticker: str, score: float) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        text=f"{ticker} evidence",
        metadata={"ticker": ticker, "company_name": f"{ticker} Company"},
        hybrid_score=score,
    )


def test_thematic_scan_diversifies_and_caps_issuer_evidence() -> None:
    diversified = diversify_candidates_by_issuer(
        [
            _candidate(1, "AAPL", 0.9),
            _candidate(2, "AAPL", 0.8),
            _candidate(3, "AAPL", 0.7),
            _candidate(4, "MSFT", 0.6),
            _candidate(5, "NVDA", 0.5),
        ],
        issuer_limit=2,
        results_per_issuer=2,
    )

    assert [issuer.ticker for issuer in diversified] == ["AAPL", "MSFT"]
    assert [len(issuer.evidence) for issuer in diversified] == [2, 1]
