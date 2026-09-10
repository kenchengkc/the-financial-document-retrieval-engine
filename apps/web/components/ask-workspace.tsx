import {
  Activity,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Database,
  FileText,
  Filter,
  Layers,
  LoaderCircle,
  Route,
  ShieldCheck,
  Timer,
} from "lucide-react";

import type { AnswerResponse } from "@/lib/types";

import {
  ConfidenceRing,
  EvidenceCard,
  FilingSourceLink,
  ResultAnalysis,
  RetrievalFunnel,
  formatLatency,
  metadataValue,
  rankDeltas,
  type SessionRun,
} from "./instruments";
import { ScanProgress } from "./scan-progress";

export type AskWorkspaceFunnel = {
  retrieved: number;
  reranked: number;
  gatePassed: boolean;
  cited: number;
};

export type AskWorkspaceScope = {
  tickers: string[];
  forms: string[];
  asOf: string | null;
};

export function AskWorkspace({
  question,
  result,
  error,
  loading,
  estimateMs,
  displayEvidence,
  funnel,
  scope,
  primaryTicker,
  primaryForm,
  primaryDate,
  primaryMetadata,
}: {
  question: string;
  result: AnswerResponse | null;
  error: string | null;
  loading: boolean;
  estimateMs: number;
  displayEvidence: AnswerResponse["evidence"];
  funnel: AskWorkspaceFunnel | null;
  scope: AskWorkspaceScope | null;
  primaryTicker: string;
  primaryForm: string;
  primaryDate: string;
  primaryMetadata: Record<string, unknown>;
}) {
  const citedChunkIds = new Set(result?.citations.map((c) => c.chunk_id) ?? []);
  const rankedEvidence = displayEvidence.filter((candidate) => candidate.rerank_score !== null);
  const contextEvidence = displayEvidence.filter((candidate) => candidate.rerank_score === null);
  const evidenceForSummary = rankedEvidence.length ? rankedEvidence : displayEvidence;
  const maxRerank = Math.max(0.0001, ...rankedEvidence.map((c) => c.rerank_score ?? 0));
  const evidenceDeltas = rankDeltas(rankedEvidence);
  const firstEvidence = evidenceForSummary[0];
  const commonTicker =
    firstEvidence && evidenceForSummary.length > 1 &&
    evidenceForSummary.every((c) => c.metadata.ticker === firstEvidence.metadata.ticker)
      ? metadataValue(firstEvidence.metadata.ticker, "") || null
      : null;
  const commonSection =
    firstEvidence && evidenceForSummary.length > 1 &&
    evidenceForSummary.every((c) => c.metadata.section === firstEvidence.metadata.section)
      ? metadataValue(firstEvidence.metadata.section, "") || null
      : null;
  const displayedConfidence = Number(
    result?.retrieval_gate.confidence ?? result?.confidence ?? 0,
  );
  const primaryAccession = metadataValue(primaryMetadata.accession_number, "");
  const primaryAcceptedAt = metadataValue(primaryMetadata.accepted_at, "");
  return (
    <div aria-live="polite">
      {error && (
        <div className="notice error" role="alert">
          <CircleAlert size={19} />
          <div>
            <strong>The API could not answer this request.</strong>
            <p>{error}</p>
          </div>
        </div>
      )}

      <div className={`result-grid${result ? " has-result" : ""}`}>
        <section className="result-column">
          {!result && (
            <div className="section-heading workspace-heading">
              <div>
                <p className="eyebrow">Question and answer</p>
                <h2>{loading ? "Searching SEC filings" : "Ready for a question"}</h2>
              </div>
            </div>
          )}

          {loading && (
            <div className="loading-state" role="status">
              <LoaderCircle className="spin" size={24} />
              <div>
                <h3>Searching SEC filings</h3>
                <p>{question}</p>
              </div>
              <ScanProgress
                estimateMs={estimateMs}
                stages={["Identify company", "Search filings", "Rank passages", "Check citations"]}
              />
            </div>
          )}

          {!result && !error && !loading && (
            <div className="empty-state">
              <Database size={28} />
              <h3>Ask a filing question above</h3>
              <p>Search a company, filing period, disclosure, table, or financial result.</p>
            </div>
          )}

          {result?.abstained && (
            <div className="notice abstain">
              <ShieldCheck size={20} />
              <div>
                <strong>No verified answer</strong>
                <p>{result.abstention_reason}</p>
              </div>
            </div>
          )}

          {result?.answer && (
            <div className="answer">
              <div className="answer-meta">
                <CheckCircle2 size={17} />
                <span>Citation text verified</span>
                <span>· {formatLatency(result.latency_ms)}</span>
              </div>
              <p className="answer-question">{result.question}</p>
              <p>{result.answer}</p>
              <footer>
                <span>
                  <FileText size={14} aria-hidden="true" />
                  {primaryTicker} · {primaryForm} · {primaryDate}
                </span>
                <FilingSourceLink metadata={primaryMetadata} />
                <span>
                  <Timer size={14} aria-hidden="true" />
                  {formatLatency(result.latency_ms)}
                </span>
                <span className="answer-run">run_{result.answer_run_id}</span>
              </footer>
            </div>
          )}

          {result && (
            <>
              <div className="section-heading evidence-title">
                <p className="eyebrow">Primary sources</p>
                <span>
                  {rankedEvidence.length} ranked passage{rankedEvidence.length === 1 ? "" : "s"}
                  {contextEvidence.length ? ` · ${contextEvidence.length} supporting` : ""}
                  {commonTicker ? ` · ${commonTicker}` : ""}
                  {commonSection ? ` · ${commonSection}` : ""}
                </span>
              </div>
              {rankedEvidence.length > 0 && <ResultAnalysis candidates={rankedEvidence} />}
              <div className="evidence-list">
                {rankedEvidence.map((candidate, index) => (
                  <EvidenceCard
                    key={candidate.chunk_id}
                    candidate={candidate}
                    index={index}
                    defaultOpen={index === 0}
                    cited={citedChunkIds.has(candidate.chunk_id)}
                    heat={(candidate.rerank_score ?? 0) / maxRerank}
                    commonTicker={commonTicker}
                    commonSection={commonSection}
                    rankDelta={evidenceDeltas.get(candidate.chunk_id)}
                  />
                ))}
              </div>
              {contextEvidence.length > 0 && (
                <details className="context-evidence">
                  <summary>
                    <span>
                      <strong>{contextEvidence.length} supporting passages</strong>
                      <small>Related passages; not used to rank results or validate the answer</small>
                    </span>
                    <ChevronDown size={16} aria-hidden="true" />
                  </summary>
                  <div className="evidence-list context-list">
                    {contextEvidence.map((candidate, index) => (
                      <EvidenceCard
                        key={candidate.chunk_id}
                        candidate={candidate}
                        index={rankedEvidence.length + index}
                        cited={citedChunkIds.has(candidate.chunk_id)}
                        commonTicker={commonTicker}
                        commonSection={commonSection}
                        context
                      />
                    ))}
                  </div>
                </details>
              )}
              {result.evidence.length === 0 && (
                <p className="muted">No source passages met the answer-quality check.</p>
              )}
            </>
          )}
        </section>

        {result && (
          <aside className="inspection">
            <section>
              <div className="aside-title">
                <Route size={17} />
                <h2>Run summary</h2>
              </div>
              <div className="run-dash">
                <div
                  className="conf-block"
                  title="60% relevance score + 40% verified citation support"
                >
                  <ConfidenceRing value={displayedConfidence} />
                  <span className="conf-caption">answer support score</span>
                </div>
                <dl className="run-stats">
                  <div>
                    <dt>Answer check</dt>
                    <dd className={result.retrieval_gate.passed ? "ok" : "hold"}>
                      {result.retrieval_gate.passed ? "Passed" : "Held"}
                    </dd>
                  </div>
                  <div>
                    <dt>Best match score</dt>
                    <dd>{Number(result.retrieval_gate.max_score ?? 0).toFixed(3)}</dd>
                  </div>
                  <div>
                    <dt>Latency</dt>
                    <dd>{formatLatency(result.latency_ms)}</dd>
                  </div>
                </dl>
              </div>
              {funnel && (
                <RetrievalFunnel
                  retrieved={funnel.retrieved}
                  reranked={funnel.reranked}
                  gatePassed={funnel.gatePassed}
                  cited={funnel.cited}
                />
              )}
              <div className="scope-row">
                <span className="scope-head">
                  <Layers size={13} aria-hidden="true" />
                    Search methods
                </span>
                <div className="route-list">
                  {result.route.map((route) => (
                    <span key={route}>{route.replaceAll("_", " ")}</span>
                  ))}
                </div>
              </div>
              {scope && (scope.tickers.length > 0 || scope.forms.length > 0) && (
                <div className="scope-row">
                  <span className="scope-head">
                    <Filter size={13} aria-hidden="true" />
                    Search scope
                  </span>
                  <div className="scope-list">
                    {scope.tickers.map((ticker) => (
                      <span key={`t-${ticker}`} className="scope-tag">
                        {ticker}
                      </span>
                    ))}
                    {scope.forms.map((form) => (
                      <span key={`f-${form}`} className="scope-tag form">
                        {form}
                      </span>
                    ))}
                    <span className="scope-tag pit">
                      {scope.asOf ? `as-of ${scope.asOf.slice(0, 10)}` : "latest available"}
                    </span>
                  </div>
                </div>
              )}
              {(primaryAccession || primaryAcceptedAt) && (
                <div className="scope-row">
                  <span className="scope-head">
                    <FileText size={13} aria-hidden="true" />
                    Source record
                  </span>
                  <div className="scope-list">
                    {primaryAccession && <span className="scope-tag accession">{primaryAccession}</span>}
                    {primaryAcceptedAt && (
                      <span className="scope-tag pit">accepted {primaryAcceptedAt.slice(0, 10)}</span>
                    )}
                    <FilingSourceLink metadata={primaryMetadata} />
                  </div>
                </div>
              )}
            </section>

            <section>
              <div className="aside-title">
                <ShieldCheck size={17} />
                <h2>Citations</h2>
              </div>
              {result.citations.length ? (
                <ol className="citations">
                  {result.citations.map((citation) => (
                    <li key={`${citation.chunk_id}-${citation.claim_text}`}>
                      <strong>
                        {metadataValue(citation.metadata.ticker, "SEC")} ·{" "}
                        {metadataValue(citation.metadata.form_type, "Filing")}
                      </strong>
                      <p>{citation.claim_text}</p>
                      <span>{Math.round(citation.confidence * 100)}% text overlap</span>
                      <FilingSourceLink metadata={citation.metadata} />
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="muted">No citations were returned.</p>
              )}
            </section>

            <details className="trace-disclosure">
              <summary>
                <span className="aside-title">
                  <Activity size={17} />
                  <strong>Processing details</strong>
                </span>
                <span>{result.trace.length} steps</span>
                <ChevronDown size={15} aria-hidden="true" />
              </summary>
              <ol className="trace">
                {result.trace.map((step, index) => (
                  <li key={`${step.node}-${index}`}>
                    <span>{index + 1}</span>
                    <div>
                      <strong>{step.node.replaceAll("_", " ")}</strong>
                      <small>{JSON.stringify(step.details)}</small>
                    </div>
                  </li>
                ))}
              </ol>
            </details>
          </aside>
        )}
      </div>
    </div>
  );
}

export type { SessionRun };
