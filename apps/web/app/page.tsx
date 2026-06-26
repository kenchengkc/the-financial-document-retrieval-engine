"use client";

import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Building2,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Database,
  FileText,
  Filter,
  GaugeCircle,
  Layers,
  LineChart,
  LoaderCircle,
  MessageSquareText,
  Route,
  ScanSearch,
  Search,
  ShieldCheck,
  Timer,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { LandingHero } from "@/components/landing-hero";
import { OperationsPanel } from "@/components/operations-panel";
import { RetrievePanel } from "@/components/retrieve-panel";
import { ScreenPanel } from "@/components/screen-panel";
import { SignalsPanel } from "@/components/signals-panel";
import { UniversePanel } from "@/components/universe-panel";
import {
  ConfidenceRing,
  EvidenceCard,
  RetrievalFunnel,
  SessionTelemetry,
  formatLatency,
  metadataValue,
  resolvedScope,
  traceCount,
  type SessionRun,
} from "@/components/instruments";
import { askQuestion, checkHealth } from "@/lib/api";
import type { AnswerResponse } from "@/lib/types";

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

type ModeId = "ask" | "retrieve" | "screen" | "signals" | "universe" | "operations";

const MODES: { id: ModeId; label: string; hint: string; icon: typeof Search }[] = [
  { id: "ask", label: "Ask", hint: "Cited answers", icon: MessageSquareText },
  { id: "retrieve", label: "Retrieve", hint: "Hybrid RAG search", icon: CalendarClock },
  { id: "screen", label: "Screen", hint: "Cross-sectional scan", icon: ScanSearch },
  { id: "signals", label: "Signals", hint: "Event-study backtest", icon: LineChart },
  { id: "universe", label: "Universe", hint: "Coverage explorer", icon: Building2 },
  { id: "operations", label: "Operations", hint: "Data quality", icon: GaugeCircle },
];

export default function Home() {
  const [mode, setMode] = useState<ModeId>("ask");
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AnswerResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingStage, setLoadingStage] = useState(0);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [history, setHistory] = useState<SessionRun[]>([]);
  const questionRef = useRef<HTMLInputElement | null>(null);
  const consoleRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    void (async () => {
      setApiOnline(await checkHealth());
    })();
  }, []);

  useEffect(() => {
    if (loading || result || error) {
      consoleRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [loading, result, error]);

  useEffect(() => {
    if (!loading) return;
    const timer = window.setInterval(() => {
      setLoadingStage((stage) => Math.min(stage + 1, 3));
    }, 6000);
    return () => window.clearInterval(timer);
  }, [loading]);

  function pushRun(run: SessionRun) {
    setHistory((previous) => [...previous, run]);
  }

  function selectMode(next: ModeId) {
    setMode(next);
    if (next !== "ask") {
      window.requestAnimationFrame(() =>
        consoleRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
      );
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim() || loading) return;
    setMode("ask");
    setLoadingStage(0);
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const response = await askQuestion(question.trim());
      setResult(response);
      setApiOnline(true);
      pushRun({
        mode: "ask",
        latencyMs: response.latency_ms,
        grounded: Boolean(response.answer) && !response.abstained,
        abstained: response.abstained,
        topScore: Number(response.retrieval_gate.max_score ?? 0),
        confidence: response.confidence ?? 0,
      });
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

  const funnel = useMemo(() => {
    if (!result) return null;
    const retrieved =
      traceCount(result.trace, "merge_candidates") ??
      traceCount(result.trace, "retrieve_text") ??
      result.evidence.length;
    const reranked = traceCount(result.trace, "rerank") ?? result.evidence.length;
    return {
      retrieved,
      reranked,
      gatePassed: Boolean(result.retrieval_gate.passed),
      cited: result.citations.length,
    };
  }, [result]);
  const scope = result ? resolvedScope(result.trace) : null;

  return (
    <div className="site-shell">
      <LandingHero
        apiOnline={apiOnline}
        onExplore={() => {
          setMode("ask");
          window.requestAnimationFrame(() =>
            consoleRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
          );
        }}
      />

      <main>
        {history.length > 0 && <SessionTelemetry runs={history} />}

        <div className="console" ref={consoleRef}>
          <div className="console-rail" role="tablist" aria-label="Research modes">
            {MODES.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={mode === item.id}
                  className={`console-tab${mode === item.id ? " on" : ""}`}
                  onClick={() => selectMode(item.id)}
                >
                  <Icon size={17} aria-hidden="true" />
                  <span>
                    <strong>{item.label}</strong>
                    <small>{item.hint}</small>
                  </span>
                </button>
              );
            })}
          </div>

          <div className="console-body">
            {mode === "ask" && (
              <>
                <form className="hd-search console-search" onSubmit={submit}>
                  <Search size={20} aria-hidden="true" />
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
                <div className="hd-chips console-chips" aria-label="Example questions">
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
                <AskWorkspace
                  question={question}
                  result={result}
                  error={error}
                  loading={loading}
                  loadingStage={loadingStage}
                  displayEvidence={displayEvidence}
                  funnel={funnel}
                  scope={scope}
                  primaryTicker={primaryTicker}
                  primaryForm={primaryForm}
                  primaryDate={primaryDate}
                />
              </>
            )}
            {mode === "retrieve" && <RetrievePanel onRun={pushRun} />}
            {mode === "screen" && <ScreenPanel onRun={pushRun} />}
            {mode === "signals" && <SignalsPanel />}
            {mode === "universe" && <UniversePanel />}
            {mode === "operations" && <OperationsPanel />}
          </div>
        </div>

        <section className="architecture">
          <div>
            <p className="eyebrow">RAG search stack</p>
            <h2>Ground retrieval before generation</h2>
            <p>
              FDRE resolves issuers and dates, searches dense and lexical indexes, reranks
              evidence, verifies citations, and abstains when support is weak.
            </p>
          </div>
          <ol>
            <li>Issuer and date-aware query routing</li>
            <li>Dense plus lexical SEC retrieval</li>
            <li>Rerank and evidence-gate candidates</li>
            <li>Citation verification before answers</li>
            <li>Point-in-time panels and signal studies</li>
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

function AskWorkspace({
  question,
  result,
  error,
  loading,
  loadingStage,
  displayEvidence,
  funnel,
  scope,
  primaryTicker,
  primaryForm,
  primaryDate,
}: {
  question: string;
  result: AnswerResponse | null;
  error: string | null;
  loading: boolean;
  loadingStage: number;
  displayEvidence: AnswerResponse["evidence"];
  funnel: { retrieved: number; reranked: number; gatePassed: boolean; cited: number } | null;
  scope: { tickers: string[]; forms: string[]; asOf: string | null } | null;
  primaryTicker: string;
  primaryForm: string;
  primaryDate: string;
}) {
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
          <div className="section-heading">
            <div>
              <p className="eyebrow">{result ? "Research answer" : "Ask workspace"}</p>
              <h2>
                {result ? result.question : loading ? "Retrieving evidence" : "Ready for a query"}
              </h2>
            </div>
            {result && <span className="run-id">Run {result.answer_run_id}</span>}
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
              <p>Search a company, filing period, disclosure, table, or financial result.</p>
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
                  <EvidenceCard
                    key={candidate.chunk_id}
                    candidate={candidate}
                    index={index}
                    defaultOpen={index === 0}
                  />
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
              <div className="run-dash">
                <div className="conf-block">
                  <ConfidenceRing value={result.confidence ?? 0} />
                  <span className="conf-caption">retrieval confidence</span>
                </div>
                <dl className="run-stats">
                  <div>
                    <dt>Evidence gate</dt>
                    <dd className={result.retrieval_gate.passed ? "ok" : "hold"}>
                      {result.retrieval_gate.passed ? "Passed" : "Held"}
                    </dd>
                  </div>
                  <div>
                    <dt>Top rerank</dt>
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
                  Routes
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
                    Resolved scope
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
    </div>
  );
}
