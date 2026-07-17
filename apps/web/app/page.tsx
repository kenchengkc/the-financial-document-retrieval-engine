"use client";

import {
  Activity,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Database,
  FileText,
  Filter,
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

import { DataFoundation } from "@/components/data-foundation";
import { LandingHero } from "@/components/landing-hero";
import { RetrievePanel } from "@/components/retrieve-panel";
import { ScanProgress } from "@/components/scan-progress";
import { ScreenPanel } from "@/components/screen-panel";
import { SignalsPanel } from "@/components/signals-panel";
import {
  ConfidenceRing,
  EvidenceCard,
  ResultAnalysis,
  RetrievalFunnel,
  formatLatency,
  metadataValue,
  rankDeltas,
  resolvedScope,
  traceCount,
  type SessionRun,
} from "@/components/instruments";
import { askQuestion, checkHealth } from "@/lib/api";
import type { AnswerResponse } from "@/lib/types";

const exampleChips = [
  {
    tag: "AAPL · text",
    label: "Supply-chain changes",
    question:
      "In its latest 10-K, what significant risks and uncertainties does Apple associate with changes or additions to its supply chain?",
  },
  {
    tag: "META · earnings",
    label: "Latest quarter",
    question: "What did META report for earnings last quarter?",
  },
  {
    tag: "no forecasts",
    label: "Unsupported request",
    question: "What will NVIDIA's stock price be next quarter?",
    abstain: true,
  },
];

type ModeId = "ask" | "retrieve" | "screen" | "signals";

const MODES: { id: ModeId; label: string; hint: string; icon: typeof Search }[] = [
  { id: "ask", label: "Ask", hint: "Cited answers from filings", icon: MessageSquareText },
  { id: "retrieve", label: "Retrieve", hint: "Hybrid search, point-in-time", icon: Search },
  { id: "screen", label: "Screen", hint: "Cross-sectional theme scan", icon: ScanSearch },
  { id: "signals", label: "Signals", hint: "Event-study backtests", icon: LineChart },
];

const STACK_STEPS = [
  { title: "Route", detail: "Issuer & date-aware query routing" },
  { title: "Retrieve", detail: "Dense + lexical SEC retrieval" },
  { title: "Rerank", detail: "Cross-encoder evidence gate" },
  { title: "Verify", detail: "Citation check before answering" },
  { title: "Study", detail: "Point-in-time panels & signals" },
];

export default function Home() {
  const [mode, setMode] = useState<ModeId>("ask");
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AnswerResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [answerMs, setAnswerMs] = useState(9_000);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [history, setHistory] = useState<SessionRun[]>([]);
  const researchRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    void (async () => {
      setApiOnline(await checkHealth());
    })();
  }, []);

  function pushRun(run: SessionRun) {
    setHistory((previous) => [...previous, run]);
  }

  function selectMode(next: ModeId) {
    setMode(next);
  }

  async function runQuestion(nextQuestion: string) {
    const normalizedQuestion = nextQuestion.trim();
    if (!normalizedQuestion || loading) return;
    setQuestion(normalizedQuestion);
    setMode("ask");
    setLoading(true);
    setResult(null);
    setError(null);
    const startedAt = performance.now();
    try {
      const response = await askQuestion(normalizedQuestion);
      const observed = performance.now() - startedAt;
      setAnswerMs((prev) =>
        Math.min(45_000, Math.max(2_500, Math.round(prev * 0.4 + observed * 0.6))),
      );
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

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void runQuestion(question);
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
            researchRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
          );
        }}
      />

      <main className="research-shell home-research" ref={researchRef}>
        <div className="research-main">
          <header className="console-title">
            <p className="eyebrow">Research console</p>
            <h1>One engine, four ways in</h1>
          </header>

          <section className="console research-console">
          <div className="console-rail mode-switcher" role="tablist" aria-label="Research modes">
            {MODES.map((item, index) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={mode === item.id}
                  className={`console-tab mode-tab${mode === item.id ? " on" : ""}`}
                  onClick={() => selectMode(item.id)}
                >
                  <span className="mode-icon">
                    <Icon size={17} aria-hidden="true" />
                  </span>
                  <span className="mode-copy">
                    <strong>{item.label}</strong>
                    <small>{item.hint}</small>
                  </span>
                  <kbd aria-hidden="true">{index + 1}</kbd>
                </button>
              );
            })}
          </div>

          <div className="console-body research-console-body" role="tabpanel">
            {mode === "ask" && (
              <div className="mode-panel ask-mode">
                <div className="panel-intro ask-intro">
                  <p className="eyebrow">Cited answers from filings</p>
                  <h2>Ask</h2>
                  <p className="panel-lede">
                    Ask a question in plain language. FDRE retrieves, reranks, verifies citations,
                    and declines when the filings do not support an answer.
                  </p>
                </div>
                <form className="hd-search research-query console-search" onSubmit={submit}>
                  <Search size={20} aria-hidden="true" />
                  <label className="sr-only" htmlFor="question">
                    Ask a financial filing question
                  </label>
                  <input
                    id="question"
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    placeholder="What did META report for earnings last quarter?"
                  />
                  <button className="go" type="submit" disabled={loading} aria-label="Search">
                    {loading ? (
                      <LoaderCircle className="spin" size={17} />
                    ) : (
                      <ArrowRight size={17} strokeWidth={1.8} />
                    )}
                    {loading ? "Retrieving" : "Ask"}
                  </button>
                </form>
                <div className="hd-chips console-chips" aria-label="Example questions">
                  {exampleChips.map((chip) => (
                    <button
                      key={chip.tag}
                      type="button"
                      className={`hd-chip${chip.abstain ? " ab" : ""}`}
                      disabled={loading}
                      onClick={() => {
                        void runQuestion(chip.question);
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
                  estimateMs={answerMs}
                  displayEvidence={displayEvidence}
                  funnel={funnel}
                  scope={scope}
                  primaryTicker={primaryTicker}
                  primaryForm={primaryForm}
                  primaryDate={primaryDate}
                />
              </div>
            )}
            {mode === "retrieve" && <RetrievePanel onRun={pushRun} />}
            {mode === "screen" && <ScreenPanel onRun={pushRun} />}
            {mode === "signals" && <SignalsPanel />}
          </div>
          </section>

          <DataFoundation runs={history} />

          <section className="research-stack" aria-labelledby="research-stack-title">
            <div className="stack-heading">
              <div>
                <p className="eyebrow">RAG search stack</p>
                <h2 id="research-stack-title">Ground retrieval before generation</h2>
              </div>
              <p>
                FDRE resolves issuers and dates, searches dense and lexical indexes, reranks
                evidence, verifies citations, and declines unsupported requests.
              </p>
            </div>
            <ol className="stack-steps">
              {STACK_STEPS.map((step, index) => (
                <li key={step.title}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <strong>{step.title}</strong>
                  <small>{step.detail}</small>
                </li>
              ))}
            </ol>
          </section>
        </div>
      </main>
    </div>
  );
}

function AskWorkspace({
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
}: {
  question: string;
  result: AnswerResponse | null;
  error: string | null;
  loading: boolean;
  estimateMs: number;
  displayEvidence: AnswerResponse["evidence"];
  funnel: { retrieved: number; reranked: number; gatePassed: boolean; cited: number } | null;
  scope: { tickers: string[]; forms: string[]; asOf: string | null } | null;
  primaryTicker: string;
  primaryForm: string;
  primaryDate: string;
}) {
  const citedChunkIds = new Set(result?.citations.map((c) => c.chunk_id) ?? []);
  const maxRerank = Math.max(0.0001, ...displayEvidence.map((c) => c.rerank_score ?? 0));
  const evidenceDeltas = rankDeltas(displayEvidence);
  const firstEvidence = displayEvidence[0];
  const commonTicker =
    firstEvidence && displayEvidence.length > 1 &&
    displayEvidence.every((c) => c.metadata.ticker === firstEvidence.metadata.ticker)
      ? metadataValue(firstEvidence.metadata.ticker, "") || null
      : null;
  const commonSection =
    firstEvidence && displayEvidence.length > 1 &&
    displayEvidence.every((c) => c.metadata.section === firstEvidence.metadata.section)
      ? metadataValue(firstEvidence.metadata.section, "") || null
      : null;
  const displayedConfidence = Number(
    result?.retrieval_gate.confidence ?? result?.confidence ?? 0,
  );
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
                <p className="eyebrow">Ask workspace</p>
                <h2>{loading ? "Retrieving evidence" : "Ready for a query"}</h2>
              </div>
            </div>
          )}

          {loading && (
            <div className="loading-state" role="status">
              <LoaderCircle className="spin" size={24} />
              <div>
                <h3>Searching indexed SEC filings</h3>
                <p>{question}</p>
              </div>
              <ScanProgress
                estimateMs={estimateMs}
                stages={["Resolve issuer", "Retrieve evidence", "Rerank sources", "Verify citations"]}
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
                <span>Citation verified</span>
                <span>· {formatLatency(result.latency_ms)}</span>
              </div>
              <p className="answer-question">{result.question}</p>
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
                <span className="answer-run">run_{result.answer_run_id}</span>
              </footer>
            </div>
          )}

          {result && (
            <>
              <div className="section-heading evidence-title">
                <p className="eyebrow">Primary sources</p>
                <span>
                  {result.evidence.length} sources
                  {commonTicker ? ` · ${commonTicker}` : ""}
                  {commonSection ? ` · ${commonSection}` : ""}
                </span>
              </div>
              {displayEvidence.length > 0 && <ResultAnalysis candidates={displayEvidence} />}
              <div className="evidence-list">
                {displayEvidence.map((candidate, index) => (
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
                <div
                  className="conf-block"
                  title="60% top rerank relevance + 40% verified citation support"
                >
                  <ConfidenceRing value={displayedConfidence} />
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
