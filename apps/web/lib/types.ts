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

export type ComponentResult = {
  signal: string;
  window: string;
  sample_size: number;
  information_coefficient: number | null;
};

export type SignalCorrelation = {
  signal_a: string;
  signal_b: string;
  correlation: number | null;
};

export type SignalConstituent = {
  ticker: string;
  name: string;
  value: number;
  side: "long" | "short";
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
    dataset_version?: string;
    feature_version?: string;
    code_sha?: string;
    event_count: number;
    config: {
      benchmark_ticker?: string;
      confidence_level?: number;
      bootstrap_iterations?: number;
      random_seed?: number;
      market_timezone?: string;
      market_close?: string;
      walk_forward_splits?: string[];
      windows?: Array<{ start: number; end: number; label: string }>;
    };
    results: SignalWindow[];
    component_signals?: string[];
    components?: ComponentResult[];
    signal_correlations?: SignalCorrelation[];
    neutralization?: string;
    constituents?: SignalConstituent[];
  };
};

export type SignalStudiesResponse = {
  studies: SignalStudyResponse[];
};

export type FilingPassageChange = {
  change_type: "added" | "removed" | "materially_changed";
  section: string;
  before_text: string | null;
  after_text: string | null;
  before_fingerprint: string | null;
  after_fingerprint: string | null;
  similarity: number | null;
};

export type FilingDifference = {
  company_ticker: string;
  current_accession: string;
  previous_accession: string;
  current_available_at: string | null;
  previous_available_at: string | null;
  comparison_basis: string;
  changes: FilingPassageChange[];
  added_count: number;
  removed_count: number;
  materially_changed_count: number;
};

export type CanonicalMetric =
  | "revenue"
  | "operating_income"
  | "net_income"
  | "eps"
  | "cash"
  | "debt"
  | "shares"
  | "capex"
  | "operating_cash_flow";

export type FinancialFact = {
  ticker: string;
  canonical_metric: CanonicalMetric;
  concept: string;
  label: string | null;
  value: string;
  unit: string | null;
  period_start: string | null;
  period_end: string | null;
  period_type: string | null;
  fiscal_year: number | null;
  fiscal_period: string | null;
  form_type: string | null;
  accession_number: string;
  filed_at: string | null;
  available_at: string | null;
  is_amendment: boolean;
  is_restatement: boolean;
  source_url: string | null;
  narrative_evidence: {
    accession_number: string;
    section: string | null;
    quote: string;
    ticker: string | null;
  } | null;
};

export type FinancialFactsResponse = {
  query: Record<string, unknown>;
  facts: FinancialFact[];
};

export type ResearchPanelRow = {
  ticker: string;
  cik: string;
  accession_number: string;
  form_type: string;
  period_end: string | null;
  accepted_at: string | null;
  available_at: string;
  is_amendment: boolean;
  filing_length_tokens: number | null;
  disclosure_similarity: number | null;
  risk_added_passages: number | null;
  risk_removed_passages: number | null;
  table_density: number | null;
  numeric_density: number | null;
  filing_delay_days: number | null;
  revenue_growth: number | null;
  operating_margin: number | null;
  net_margin: number | null;
  capex_to_revenue: number | null;
  operating_cash_flow_to_revenue: number | null;
  source_accessions: string[];
  feature_provenance: Record<string, string[]>;
  calculation_version: string;
  corpus_snapshot_id: string;
  max_source_available_at: string;
};

export type ResearchPanel = {
  query: Record<string, unknown>;
  feature_version: string;
  corpus_snapshot_id: string;
  rows: ResearchPanelRow[];
};

export type UnchunkedDocument = {
  document_id: number;
  ticker: string;
  accession_number: string;
  form_type: string;
  filing_date: string | null;
  local_path: string | null;
  element_count: number;
  reason: string;
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
  unchunked_documents: UnchunkedDocument[];
  chunks_without_embeddings: number;
  facts_without_documents: number;
  freshness_ratio: number;
  document_chunk_coverage: number;
  embedding_coverage: number;
  recent_ingestion_success_rate: number;
  latest_ingestion_completed_at: string | null;
};
