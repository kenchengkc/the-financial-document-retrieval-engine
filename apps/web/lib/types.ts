export type RetrievalCandidate = {
  chunk_id: number;
  text: string;
  metadata: Record<string, unknown>;
  dense_score: number | null;
  sparse_score: number | null;
  hybrid_score: number | null;
  rerank_score: number | null;
  rank: number | null;
};

export type VerifiedCitation = {
  chunk_id: number;
  claim_text: string;
  citation_text: string;
  metadata: Record<string, unknown>;
  confidence: number;
};

export type TraceStep = {
  node: string;
  details: Record<string, unknown>;
};

export type CoverageResponse = {
  catalog_count: number;
  sp500_catalog_count: number;
  indexed_count: number;
  sp500_indexed_count: number;
  document_count: number;
  chunk_count: number;
  indexed_tickers: string[];
};

export type AnswerResponse = {
  answer_run_id: number;
  question: string;
  rewritten_queries: string[];
  route: string[];
  answer: string | null;
  confidence: number | null;
  abstained: boolean;
  abstention_reason: string | null;
  evidence: RetrievalCandidate[];
  citations: VerifiedCitation[];
  financial_facts: Record<string, unknown>[];
  retrieval_gate: Record<string, unknown>;
  trace: TraceStep[];
  latency_ms: number;
};
