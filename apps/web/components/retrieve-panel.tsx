"use client";

import {
  ArrowRight,
  CalendarClock,
  CircleAlert,
  LoaderCircle,
  SlidersHorizontal,
} from "lucide-react";
import { FormEvent, useState } from "react";

import { runSearch } from "@/lib/api";
import type { SearchFilters, SearchResponse } from "@/lib/types";

import {
  EvidenceCard,
  ResultAnalysis,
  formatLatency,
  rankDeltas,
  type SessionRun,
} from "./instruments";

const FORM_OPTIONS = ["10-K", "10-Q", "8-K"];

function splitList(value: string): string[] {
  return value
    .split(/[,\s]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function RetrievePanel({ onRun }: { onRun?: (run: SessionRun) => void }) {
  const [query, setQuery] = useState("");
  const [tickers, setTickers] = useState("");
  const [sections, setSections] = useState("");
  const [forms, setForms] = useState<string[]>([]);
  const [asOf, setAsOf] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  function toggleForm(form: string) {
    setForms((current) =>
      current.includes(form) ? current.filter((item) => item !== form) : [...current, form],
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!query.trim() || loading) return;
    setLoading(true);
    setError(null);
    const filters: SearchFilters = {};
    const tickerList = splitList(tickers).map((item) => item.toUpperCase());
    if (tickerList.length) filters.tickers = tickerList;
    if (forms.length) filters.form_types = forms;
    if (sections.trim()) filters.sections = [sections.trim()];
    if (asOf) filters.as_of = `${asOf}T00:00:00+00:00`;
    try {
      const response = await runSearch(query.trim(), filters, 8);
      setResult(response);
      const top = response.results[0]?.rerank_score ?? 0;
      onRun?.({
        mode: "retrieve",
        latencyMs: response.latency_ms,
        grounded: response.results.length > 0,
        abstained: false,
        topScore: top ?? 0,
        confidence: 0,
      });
    } catch (cause) {
      setResult(null);
      setError(cause instanceof Error ? cause.message : "The search failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mode-panel">
      <div className="panel-intro">
        <p className="eyebrow">Point-in-time RAG retrieval</p>
        <h2>Hybrid RAG search with a knowable-as-of boundary</h2>
        <p className="panel-lede">
          Dense vectors, lexical search, reranking, and citation-aware metadata over SEC filings.
          Set an as-of date to constrain evidence to what was public on that day.
        </p>
      </div>

      <form className="retrieve-form" onSubmit={submit}>
        <div className="rf-query">
          <SlidersHorizontal size={18} aria-hidden="true" />
          <input
            aria-label="Search query"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="e.g. data center capital expenditure commitments"
          />
          <button type="submit" disabled={loading}>
            {loading ? <LoaderCircle className="spin" size={16} /> : <ArrowRight size={16} />}
            {loading ? "Retrieving" : "Retrieve"}
          </button>
        </div>

        <div className="rf-controls">
          <label className="rf-field">
            <span>Tickers</span>
            <input
              value={tickers}
              onChange={(event) => setTickers(event.target.value)}
              placeholder="AAPL, MSFT"
            />
          </label>
          <label className="rf-field">
            <span>Section contains</span>
            <input
              value={sections}
              onChange={(event) => setSections(event.target.value)}
              placeholder="Risk Factors"
            />
          </label>
          <label className="rf-field rf-asof">
            <span>
              <CalendarClock size={12} aria-hidden="true" /> As-of date
            </span>
            <input
              type="date"
              value={asOf}
              onChange={(event) => setAsOf(event.target.value)}
            />
          </label>
          <div className="rf-field rf-forms">
            <span>Form type</span>
            <div className="rf-chips">
              {FORM_OPTIONS.map((form) => (
                <button
                  key={form}
                  type="button"
                  className={forms.includes(form) ? "on" : undefined}
                  onClick={() => toggleForm(form)}
                >
                  {form}
                </button>
              ))}
            </div>
          </div>
        </div>
      </form>

      {error && (
        <div className="notice error" role="alert">
          <CircleAlert size={19} />
          <div>
            <strong>Search failed</strong>
            <p>{error}</p>
          </div>
        </div>
      )}

      {result && (
        <div className="retrieve-results">
          <div className="rr-summary">
            <span>
              <strong>{result.results.length}</strong> ranked passages
            </span>
            <span>{formatLatency(result.latency_ms)}</span>
            <span className={asOf ? "pit-on" : "pit-off"}>
              <CalendarClock size={13} aria-hidden="true" />
              {asOf ? `Knowable as of ${asOf}` : "Latest available"}
            </span>
          </div>
          {result.results.length === 0 ? (
            <p className="muted">No passages matched these filters.</p>
          ) : (
            (() => {
              const deltas = rankDeltas(result.results);
              return (
                <>
                  <ResultAnalysis candidates={result.results} />
                  <div className="evidence-list">
                    {result.results.map((candidate, index) => (
                      <EvidenceCard
                        key={candidate.chunk_id}
                        candidate={candidate}
                        index={index}
                        defaultOpen={index === 0}
                        rankDelta={deltas.get(candidate.chunk_id)}
                      />
                    ))}
                  </div>
                </>
              );
            })()
          )}
        </div>
      )}

      {!result && !error && !loading && (
        <div className="empty-state compact">
          <CalendarClock size={26} />
          <h3>Run a point-in-time retrieval</h3>
          <p>
            Try the same query with and without an as-of date to see lookahead evidence drop out.
          </p>
        </div>
      )}
    </div>
  );
}
