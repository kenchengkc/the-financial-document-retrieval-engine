"use client";

import Link from "next/link";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Code2,
  Database,
  FileText,
  LoaderCircle,
  Route,
  Search,
  ShieldCheck,
  Timer,
} from "lucide-react";
import { FormEvent, useEffect, useRef, useState } from "react";

import { askQuestion, checkHealth, fetchCoverage } from "@/lib/api";
import type { AnswerResponse, CoverageResponse, RetrievalCandidate } from "@/lib/types";

const exampleChips = [
  {
    tag: "AAPL · text",
    label: "Supply-chain risk",
    question: "What did Apple say about supply chain risk in its latest 10-K?",
  },
  {
    tag: "META · earnings",
    label: "Latest quarter",
    question: "What did META report for earnings last quarter?",
  },
  {
    tag: "abstain",
    label: "Price forecast",
    question: "What will NVIDIA's stock price be next quarter?",
    abstain: true,
  },
];

function score(value: number | null) {
  return value === null ? "n/a" : value.toFixed(3);
}

function metadataValue(value: unknown, fallback: string) {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function formatLatency(latencyMs: number) {
  return latencyMs < 1000 ? `${latencyMs} ms` : `${(latencyMs / 1000).toFixed(1)} s`;
}

function Wave({ cls }: { cls: string }) {
  return (
    <svg className={`gh-wave ${cls}`} viewBox="0 0 1200 120" preserveAspectRatio="none">
      <path d="M0,58 C200,42 400,70 600,56 C800,42 1000,68 1200,54 L1200,120 L0,120 Z" />
    </svg>
  );
}

function SunsetScene() {
  return (
    <div className="gh-scene" aria-hidden="true">
      <div className="gh-sky" />
      <div className="gh-glow" />
      <div className="gh-rays" />
      <div className="gh-cloud c1" />
      <div className="gh-cloud c2" />
      <div className="gh-cloud c3" />
      <div className="gh-sun" />
      <div className="gh-horizon" />
      <div className="gh-sea">
        <div className="gh-sun-sub" />
        <div className="gh-reflect" />
        <div className="gh-waves">
          <Wave cls="w1" />
          <Wave cls="w2" />
          <Wave cls="w3" />
          <Wave cls="w4" />
          <Wave cls="w5" />
        </div>
      </div>
      <div className="gh-mist" />
      <div className="gh-grain" />
      <div className="gh-scrim" />
    </div>
  );
}

function Evidence({ candidate, index }: { candidate: RetrievalCandidate; index: number }) {
  const metadata = candidate.metadata;
  const ticker = metadataValue(metadata.ticker, "Document");
  const formType = metadataValue(metadata.form_type, "Filing");
  const section = metadataValue(metadata.section, "Unsectioned");
  const filingDate = metadataValue(metadata.filing_date, "Date unavailable");

  return (
    <details className="evidence" open={index === 0 ? true : undefined}>
      <summary>
        <span className="evidence-rank">{String(index + 1).padStart(2, "0")}</span>
        <span className="evidence-source">
          <strong>{ticker}</strong>
          <span>
            {formType} · {filingDate}
          </span>
        </span>
        <span className="evidence-section">{section}</span>
        <span className="evidence-score">{score(candidate.rerank_score)} rerank</span>
        <ChevronDown size={16} aria-hidden="true" />
      </summary>
      <div className="evidence-body">
        <p>{candidate.text}</p>
        <dl className="scores">
          <div>
            <dt>Dense</dt>
            <dd>{score(candidate.dense_score)}</dd>
          </div>
          <div>
            <dt>Sparse</dt>
            <dd>{score(candidate.sparse_score)}</dd>
          </div>
          <div>
            <dt>Hybrid</dt>
            <dd>{score(candidate.hybrid_score)}</dd>
          </div>
          <div>
            <dt>Rerank</dt>
            <dd>{score(candidate.rerank_score)}</dd>
          </div>
        </dl>
      </div>
    </details>
  );
}

export default function Home() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AnswerResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingStage, setLoadingStage] = useState(0);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [coverage, setCoverage] = useState<CoverageResponse | null>(null);
  const questionRef = useRef<HTMLInputElement | null>(null);
  const resultsRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    void (async () => {
      const online = await checkHealth();
      setApiOnline(online);
      if (online) {
        setCoverage(await fetchCoverage());
      }
    })();
  }, []);

  useEffect(() => {
    if (loading || result || error) {
      resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [loading, result, error]);

  useEffect(() => {
    if (!loading) return;
    const timer = window.setInterval(() => {
      setLoadingStage((stage) => Math.min(stage + 1, 3));
    }, 6000);
    return () => window.clearInterval(timer);
  }, [loading]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim() || loading) return;
    setLoadingStage(0);
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      setResult(await askQuestion(question.trim()));
      setApiOnline(true);
    } catch (cause) {
      setResult(null);
      setApiOnline(false);
      setError(cause instanceof Error ? cause.message : "The request failed.");
    } finally {
      setLoading(false);
    }
  }

  const citedChunkIds = new Set(result?.citations.map((citation) => citation.chunk_id) ?? []);
  const displayEvidence = result
    ? [...result.evidence].sort(
        (left, right) =>
          Number(citedChunkIds.has(right.chunk_id)) - Number(citedChunkIds.has(left.chunk_id)),
      )
    : [];
  const primaryMetadata =
    result?.citations[0]?.metadata ?? result?.evidence[0]?.metadata ?? {};
  const primaryTicker = metadataValue(primaryMetadata.ticker, "SEC filing");
  const primaryForm = metadataValue(primaryMetadata.form_type, "Filing");
  const primaryDate = metadataValue(primaryMetadata.filing_date, "Date unavailable");

  return (
    <div className="site-shell">
      <section className="hero">
        <SunsetScene />

        <header className="hd-nav">
          <Link className="hd-brand" href="/" aria-label="FDRE home">
            <span className="hd-mark">F</span>
            <span>
              <strong>FDRE</strong>
              <small>thefdre.com</small>
            </span>
          </Link>
          <nav className="hd-links" aria-label="Site">
            <Link className="on" href="/">
              Search
            </Link>
            <Link href="/about">About</Link>
          </nav>
          <div className="hd-right">
            {coverage && (
              <span
                className="coverage-badge"
                title="Companies with embedded chunks searchable via RAG"
              >
                <Database size={14} aria-hidden="true" />
                <span>
                  {coverage.indexed_count.toLocaleString()} /{" "}
                  {coverage.catalog_count.toLocaleString()} indexed
                </span>
                <span className="coverage-divider" aria-hidden="true">
                  |
                </span>
                <span>
                  S&amp;P 500: {coverage.sp500_indexed_count} / {coverage.sp500_catalog_count}
                </span>
              </span>
            )}
            <span className={`hd-status ${apiOnline === true ? "online" : ""}`}>
              <span className="dot" aria-hidden="true" />
              {apiOnline === null ? "Checking API" : apiOnline ? "API online" : "API unavailable"}
            </span>
            <a
              className="hd-pill"
              href="https://github.com/kenchengkc/the-financial-document-retrieval-engine"
              target="_blank"
              rel="noreferrer"
            >
              <Code2 size={16} aria-hidden="true" />
              <span className="hd-pill-label">View source</span>
            </a>
          </div>
        </header>

        <div className="gh-inner">
          <div className="gh-copy">
            <p className="hd-eyebrow">Research infrastructure for funds and trading firms</p>
            <h1>Financial Document Retrieval Engine</h1>
            <p className="lede">
              Point-in-time SEC filing retrieval, structured XBRL facts, filing-change analysis,
              and reproducible research exports with evidence behind every result.
            </p>

            <form className="hd-search gh-form" onSubmit={submit}>
              <Search size={22} aria-hidden="true" />
              <label className="sr-only" htmlFor="question">
                Ask a financial filing question
              </label>
              <input
                id="question"
                ref={questionRef}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="Ask about a filing, table, risk factor, or financial fact…"
              />
              <button className="go" type="submit" disabled={loading}>
                {loading ? (
                  <LoaderCircle className="spin" size={17} />
                ) : (
                  <ArrowRight size={17} strokeWidth={1.8} />
                )}
                {loading ? "Retrieving" : "Search"}
              </button>
            </form>

            <div className="hd-chips gh-chips" aria-label="Example questions">
              {exampleChips.map((chip) => (
                <button
                  key={chip.tag}
                  type="button"
                  className={`hd-chip${chip.abstain ? " ab" : ""}`}
                  onClick={() => {
                    setQuestion(chip.question);
                    questionRef.current?.focus();
                  }}
                >
                  <span className="k">{chip.tag}</span>
                  {chip.label}
                </button>
              ))}
            </div>

            <div className="gh-trust">
              <span>499 S&amp;P 500 names</span>
              <span className="sep" aria-hidden="true" />
              <span>1,065,227 embedded chunks</span>
              <span className="sep" aria-hidden="true" />
              <span>Point-in-time and citation-audited</span>
            </div>
          </div>
        </div>
      </section>

      <main ref={resultsRef}>
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
          <section className="result-column" aria-live="polite">
            <div className="section-heading">
              <div>
                <p className="eyebrow">{result ? "Research answer" : "Search workspace"}</p>
                <h2>
                  {result
                    ? result.question
                    : loading
                      ? "Retrieving evidence"
                      : "Ready for a query"}
                </h2>
              </div>
              {result && (
                <span className="run-id">Run {result.answer_run_id}</span>
              )}
            </div>

            {loading && (
              <div className="loading-state" role="status">
                <LoaderCircle className="spin" size={24} />
                <div>
                  <h3>Searching indexed SEC filings</h3>
                  <p>{question}</p>
                </div>
                <ol aria-label="Retrieval stages">
                  {["Resolve issuer", "Retrieve evidence", "Rerank sources", "Verify citations"].map(
                    (stage, index) => (
                      <li
                        key={stage}
                        className={
                          index === loadingStage
                            ? "active"
                            : index < loadingStage
                              ? "complete"
                              : undefined
                        }
                        aria-current={index === loadingStage ? "step" : undefined}
                      >
                        {stage}
                      </li>
                    ),
                  )}
                </ol>
              </div>
            )}

            {!result && !error && !loading && (
              <div className="empty-state">
                <Database size={28} />
                <h3>Ask a filing question above</h3>
                <p>
                  Search a company, filing period, disclosure, table, or financial result.
                </p>
              </div>
            )}

            {result?.abstained && (
              <div className="notice abstain">
                <ShieldCheck size={20} />
                <div>
                  <strong>FDRE abstained</strong>
                  <p>{result.abstention_reason}</p>
                </div>
              </div>
            )}

            {result?.answer && (
              <div className="answer">
                <div className="answer-meta">
                  <CheckCircle2 size={17} />
                  <span>Citation verified</span>
                  <span>{Math.round((result.confidence ?? 0) * 100)}% retrieval confidence</span>
                </div>
                <p>{result.answer}</p>
                <footer>
                  <span>
                    <FileText size={14} aria-hidden="true" />
                    {primaryTicker} · {primaryForm} · {primaryDate}
                  </span>
                  <span>
                    <Timer size={14} aria-hidden="true" />
                    {formatLatency(result.latency_ms)}
                  </span>
                </footer>
              </div>
            )}

            {result && (
              <>
                <div className="section-heading evidence-title">
                  <div>
                    <p className="eyebrow">Primary sources</p>
                    <h2>Sources supporting this answer</h2>
                  </div>
                  <span>{result.evidence.length} sources</span>
                </div>
                <div className="evidence-list">
                  {displayEvidence.map((candidate, index) => (
                    <Evidence key={candidate.chunk_id} candidate={candidate} index={index} />
                  ))}
                  {result.evidence.length === 0 && (
                    <p className="muted">No evidence passed the retrieval gate.</p>
                  )}
                </div>
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
                <div className="route-list">
                  {result.route.map((route) => (
                    <span key={route}>{route.replaceAll("_", " ")}</span>
                  ))}
                </div>
                <dl className="gate">
                  <div>
                    <dt>Evidence gate</dt>
                    <dd>{result.retrieval_gate.passed ? "Passed" : "Abstained"}</dd>
                  </div>
                  <div>
                    <dt>Top score</dt>
                    <dd>{Number(result.retrieval_gate.max_score ?? 0).toFixed(3)}</dd>
                  </div>
                  <div>
                    <dt>Sources</dt>
                    <dd>{result.evidence.length}</dd>
                  </div>
                  <div>
                    <dt>Latency</dt>
                    <dd>{formatLatency(result.latency_ms)}</dd>
                  </div>
                </dl>
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
                    <strong>Workflow trace</strong>
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

        <section className="architecture">
          <div>
            <p className="eyebrow">RAG stack</p>
            <h2>Index offline, retrieve live</h2>
            <p>
              FDRE converts SEC filings into auditable research data: hybrid retrieval for
              evidence discovery, typed XBRL facts, point-in-time feature panels, and persisted
              experiment manifests.
            </p>
          </div>
          <ol>
            <li>Single-name risk retrieval with stable evidence</li>
            <li>Table and XBRL fact extraction</li>
            <li>Comparable-period filing differences</li>
            <li>Issuer-diversified thematic scans</li>
            <li>Point-in-time panel export and event studies</li>
          </ol>
          <a
            href="https://github.com/kenchengkc/the-financial-document-retrieval-engine#architecture"
            target="_blank"
            rel="noreferrer"
          >
            Architecture <ArrowUpRight size={15} />
          </a>
        </section>
      </main>
    </div>
  );
}
