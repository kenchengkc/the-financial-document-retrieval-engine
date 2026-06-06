"use client";

import Image from "next/image";
import Link from "next/link";
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  CircleAlert,
  Code2,
  Database,
  FileSearch,
  LoaderCircle,
  Route,
  Search,
  ShieldCheck,
} from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { askQuestion, checkHealth } from "@/lib/api";
import type { AnswerResponse, RetrievalCandidate } from "@/lib/types";

const examples = [
  "What could affect Example Company's operating results?",
  "Find the table showing Example Company revenue",
  "Compare Example Company revenue growth with management commentary",
];

function score(value: number | null) {
  return value === null ? "n/a" : value.toFixed(3);
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
  const [question, setQuestion] = useState(examples[0]);
  const [result, setResult] = useState<AnswerResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);

  useEffect(() => {
    checkHealth().then(setApiOnline);
  }, []);

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
      <header className="topbar">
        <Link className="brand" href="/" aria-label="FDRE home">
          <span className="brand-mark">
            <FileSearch size={17} />
          </span>
          <span>
            <strong>FDRE</strong>
            <small>Financial Document Retrieval Engine</small>
          </span>
        </Link>
        <nav aria-label="Project links">
          <span className={`status ${apiOnline === true ? "online" : ""}`}>
            <Activity size={14} />
            {apiOnline === null ? "Checking API" : apiOnline ? "API online" : "API unavailable"}
          </span>
          <a
            href="https://github.com/kenchengkc/the-financial-document-retrieval-engine"
            target="_blank"
            rel="noreferrer"
            aria-label="View FDRE source on GitHub"
            title="View source"
          >
            <Code2 size={18} />
          </a>
        </nav>
      </header>

      <main>
        <section className="workspace-intro">
          <div>
            <p className="eyebrow">Evidence-first financial search</p>
            <h1>Financial Document Retrieval Engine</h1>
            <p>
              Ask a filing question. FDRE preprocesses it, retrieves and reranks evidence,
              verifies every citation, and abstains when the evidence is not strong enough.
            </p>
          </div>
          <Image
            src="/sample-filing.png"
            width={360}
            height={180}
            alt="Rendered sample SEC filing with a revenue table"
            priority
          />
        </section>

        <form className="query-form" onSubmit={submit}>
          <Search size={20} aria-hidden="true" />
          <label className="sr-only" htmlFor="question">
            Ask a financial filing question
          </label>
          <input
            id="question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask about an SEC filing, table, risk, or financial fact"
          />
          <button type="submit" disabled={loading}>
            {loading ? <LoaderCircle className="spin" size={18} /> : <Search size={18} />}
            {loading ? "Retrieving" : "Search evidence"}
          </button>
        </form>

        <div className="examples" aria-label="Example questions">
          {examples.map((example) => (
            <button key={example} type="button" onClick={() => setQuestion(example)}>
              {example}
            </button>
          ))}
        </div>

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
                <h3>Inspect the complete retrieval path</h3>
                <p>
                  Results include deterministic filters, dense and sparse scores, reranking,
                  verified citations, and every bounded graph transition.
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
            <p className="eyebrow">Bounded workflow</p>
            <h2>Context engineering before generation</h2>
          </div>
          <ol>
            <li>Deterministic preprocessing</li>
            <li>Dense + sparse retrieval</li>
            <li>Reranking and evidence gate</li>
            <li>Citation verification</li>
            <li>Answer or abstention</li>
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
