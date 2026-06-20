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

export type SearchFilters = {
  tickers?: string[];
  form_types?: string[];
  sections?: string[];
  as_of?: string | null;
  amendment_policy?: "include" | "exclude" | "only";
};

export type SearchResponse = {
  query: string;
  rewritten_queries: string[];
  filters: Record<string, unknown>;
  results: RetrievalCandidate[];
  latency_ms: number;
};

export type IssuerEvidence = {
  ticker: string;
  company_name: string;
  evidence: RetrievalCandidate[];
};

export type ThematicScanResponse = {
  query: string;
  filters: Record<string, unknown>;
  issuer_count: number;
  issuers: IssuerEvidence[];
  latency_ms: number;
};

export type Company = {
  ticker: string;
  cik: string;
  name: string;
  exchange: string | null;
  document_count: number;
  chunk_count: number;
  indexed: boolean;
};

export type CompaniesResponse = {
  total: number;
  companies: Company[];
};

export type SignalQuantile = {
  quantile: number;
  sample_size: number;
  mean_abnormal_return: number | null;
};

export type SignalWindow = {
  window: string;
  sample_size: number;
  information_coefficient: number | null;
  ic_t_stat: number | null;
  quantiles: SignalQuantile[];
  long_short_mean: number | null;
  long_short_ci_low: number | null;
  long_short_ci_high: number | null;
  long_short_p_value: number | null;
  long_short_adjusted_p_value: number | null;
};

export type SignalStudyResponse = {
  experiment_id: number;
  experiment_key: string;
  code_sha: string;
  created_at: string;
  report: {
    signal_name: string;
    outcome_name?: string;
    n_quantiles: number;
    event_count: number;
    config: { benchmark_ticker?: string; confidence_level?: number };
    results: SignalWindow[];
  };
};

export type SignalStudiesResponse = {
  studies: SignalStudyResponse[];
};

export type OperationsQuality = {
  generated_at: string;
  company_count: number;
  document_count: number;
  chunk_count: number;
  embedding_count: number;
  stale_after_days: number;
  stale_tickers: string[];
  missing_expected_filings: string[];
  duplicate_accession_groups: number;
  documents_without_chunks: number;
  chunks_without_embeddings: number;
  facts_without_documents: number;
  freshness_ratio: number;
  document_chunk_coverage: number;
  embedding_coverage: number;
  recent_ingestion_success_rate: number;
  latest_ingestion_completed_at: string | null;
};
