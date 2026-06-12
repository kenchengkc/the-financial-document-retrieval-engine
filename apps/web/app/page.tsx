"use client";

import Link from "next/link";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  CheckCircle2,
  CircleAlert,
  Database,
  LoaderCircle,
  Route,
  Search,
  ShieldCheck,
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
    tag: "MSFT · table",
    label: "Segment revenue",
    question: "Find the table showing Microsoft revenue by segment.",
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
  return (
    <article className="evidence">
      <header className="evidence-header">
        <span className="rank">#{index + 1}</span>
        <strong>{String(metadata.ticker ?? "Document")}</strong>
        <span>{String(metadata.form_type ?? "Filing")}</span>
        <span>{String(metadata.section ?? "Unsectioned")}</span>
      </header>
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
    </article>
  );
}

export default function Home() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AnswerResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
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
    if (result || error) {
      resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [result, error]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim() || loading) return;
    setLoading(true);
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
              View source
            </a>
          </div>
        </header>

        <div className="gh-inner">
          <div className="gh-copy">
            <p className="hd-eyebrow">For hedge funds &amp; research desks</p>
            <h1>
              Evidence you can <span className="accent">cite</span>. Answers you can trust.
            </h1>
            <p className="lede">
              FDRE searches SEC filings, ranks and verifies the evidence behind every claim, and
              abstains when it isn&apos;t strong enough — so each answer opens straight to its
              source.
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
              <span>SEC EDGAR primary sources</span>
              <span className="sep" aria-hidden="true" />
              <span>Hybrid retrieval + reranking</span>
              <span className="sep" aria-hidden="true" />
              <span>Citation-verified</span>
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

        <div className="result-grid">
          <section className="result-column" aria-live="polite">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Answer</p>
                <h2>{result ? "Grounded response" : "Ready for a query"}</h2>
              </div>
              {result && (
                <span className="run-id">Run #{result.answer_run_id}</span>
              )}
            </div>

            {!result && !error && (
              <div className="empty-state">
                <Database size={28} />
                <h3>Live RAG retrieval over indexed filings</h3>
                <p>
                  Queries hit pre-built vector and FTS indexes in PostgreSQL, then the agent
                  reranks evidence, verifies citations, and returns a full graph trace — dense,
                  sparse, hybrid, and rerank scores for every chunk.
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
                  <span>Verified citations</span>
                  <span>{Math.round((result.confidence ?? 0) * 100)}% confidence</span>
                </div>
                <p>{result.answer}</p>
              </div>
            )}

            {result && (
              <>
                <div className="section-heading evidence-title">
                  <div>
                    <p className="eyebrow">Ranked context</p>
                    <h2>Retrieved evidence</h2>
                  </div>
                  <span>{result.evidence.length} chunks</span>
                </div>
                <div className="evidence-list">
                  {result.evidence.map((candidate, index) => (
                    <Evidence key={candidate.chunk_id} candidate={candidate} index={index} />
                  ))}
                  {result.evidence.length === 0 && (
                    <p className="muted">No evidence passed the retrieval gate.</p>
                  )}
                </div>
              </>
            )}
          </section>

          <aside className="inspection">
            <section>
              <div className="aside-title">
                <Route size={17} />
                <h2>Agent route</h2>
              </div>
              <div className="route-list">
                {(result?.route ?? ["text", "tables", "financial facts"]).map((route) => (
                  <span key={route}>{route.replaceAll("_", " ")}</span>
                ))}
              </div>
              {result && (
                <dl className="gate">
                  <div>
                    <dt>Gate</dt>
                    <dd>{result.retrieval_gate.passed ? "passed" : "abstained"}</dd>
                  </div>
                  <div>
                    <dt>Max score</dt>
                    <dd>{Number(result.retrieval_gate.max_score ?? 0).toFixed(3)}</dd>
                  </div>
                </dl>
              )}
            </section>

            <section>
              <div className="aside-title">
                <ShieldCheck size={17} />
                <h2>Citations</h2>
              </div>
              {result?.citations.length ? (
                <ol className="citations">
                  {result.citations.map((citation) => (
                    <li key={`${citation.chunk_id}-${citation.claim_text}`}>
                      <strong>Chunk {citation.chunk_id}</strong>
                      <p>{citation.claim_text}</p>
                      <span>{Math.round(citation.confidence * 100)}% text overlap</span>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="muted">Verified sources appear after a successful answer.</p>
              )}
            </section>

            <section>
              <div className="aside-title">
                <Activity size={17} />
                <h2>Graph trace</h2>
              </div>
              <ol className="trace">
                {(result?.trace ?? [
                  { node: "preprocess_query", details: {} },
                  { node: "hybrid_retrieve", details: {} },
                  { node: "verify_citations", details: {} },
                ]).map((step, index) => (
                  <li key={`${step.node}-${index}`}>
                    <span>{index + 1}</span>
                    <div>
                      <strong>{step.node.replaceAll("_", " ")}</strong>
                      {result && <small>{JSON.stringify(step.details)}</small>}
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          </aside>
        </div>

        <section className="architecture">
          <div>
            <p className="eyebrow">RAG stack</p>
            <h2>Index offline, retrieve live</h2>
            <p>
              FDRE batch-indexes filings into a <strong>pgvector</strong> store, then runs a
              bounded <strong>LangGraph retrieval agent</strong> on every question: hybrid
              embedding + keyword search, reranking, verified citations, and abstention when
              evidence is weak.
            </p>
          </div>
          <ol>
            <li>Batch ingest: parse filings, chunk text and tables</li>
            <li>Vector index: embed chunks into pgvector (Voyage)</li>
            <li>Live query: hybrid RAG + rerank via LangGraph agent</li>
            <li>Citation verification on every claim</li>
            <li>Answer or abstention — no hallucination fallback</li>
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
