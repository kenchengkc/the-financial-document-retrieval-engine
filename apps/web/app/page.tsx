"use client";

import {
  ArrowRight,
  LineChart,
  LoaderCircle,
  MessageSquareText,
  ScanSearch,
  Search,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { AskWorkspace, type SessionRun } from "@/components/ask-workspace";
import { DataFoundation } from "@/components/data-foundation";
import { LandingHero } from "@/components/landing-hero";
import { RetrievePanel } from "@/components/retrieve-panel";
import { ScreenPanel } from "@/components/screen-panel";
import { SignalsPanel } from "@/components/signals-panel";
import { metadataValue, resolvedScope, traceCount } from "@/components/instruments";
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
  { id: "ask", label: "Ask", hint: "Answers with filing citations", icon: MessageSquareText },
  { id: "retrieve", label: "Retrieve", hint: "Search filing text and data", icon: Search },
  { id: "screen", label: "Screen", hint: "Compare company filings", icon: ScanSearch },
  { id: "signals", label: "Signals", hint: "Filing event studies", icon: LineChart },
];

const STACK_STEPS = [
  { title: "Identify", detail: "Company and date filters" },
  { title: "Search", detail: "Keyword and semantic search" },
  { title: "Rank", detail: "Rank the most relevant passages" },
  { title: "Validate", detail: "Check citations before answering" },
  { title: "Analyze", detail: "Historical datasets and studies" },
];

export default function Home() {
  const [mode, setMode] = useState<ModeId>("ask");
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AnswerResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [answerMs, setAnswerMs] = useState(9_000);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [latestIngestionAt, setLatestIngestionAt] = useState<string | null>(null);
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
        latestIngestionAt={latestIngestionAt}
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
            <p className="eyebrow">Research tools</p>
            <h1>Research SEC filings four ways</h1>
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
                  <p className="eyebrow">Answers with filing citations</p>
                  <h2>Ask</h2>
                  <p className="panel-lede">
                    Ask a question in plain language. FDRE searches filings, ranks relevant
                    passages, checks citations, and says when the filings do not support an answer.
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
                  primaryMetadata={primaryMetadata}
                />
              </div>
            )}
            {mode === "retrieve" && <RetrievePanel onRun={pushRun} />}
            {mode === "screen" && <ScreenPanel onRun={pushRun} />}
            {mode === "signals" && <SignalsPanel />}
          </div>
          </section>

          <DataFoundation
            runs={history}
            onOperations={(operations) =>
              setLatestIngestionAt(operations?.latest_ingestion_completed_at ?? null)
            }
          />

          <section className="research-stack" aria-labelledby="research-stack-title">
            <div className="stack-heading">
              <div>
                <p className="eyebrow">Retrieval and answer pipeline</p>
                <h2 id="research-stack-title">Find and check source text before writing an answer</h2>
              </div>
              <p>
                FDRE identifies the company and date, searches filing text and financial data,
                ranks the results, checks citations, and declines unsupported requests.
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
