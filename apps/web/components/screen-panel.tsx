"use client";

import {
  ArrowRight,
  CircleAlert,
  LoaderCircle,
  ScanSearch,
} from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { runThematicScan } from "@/lib/api";
import type { ThematicScanResponse } from "@/lib/types";

import { metadataValue, score, formatLatency, type SessionRun } from "./instruments";
import { ScanProgress } from "./scan-progress";

// Starting guess before we have measured a real scan; refined adaptively below.
const DEFAULT_SCAN_MS = 28_000;

const SCAN_STAGES = [
  "Retrieving across the indexed universe",
  "Reranking cross-encoder candidates",
  "Diversifying evidence by issuer",
];

const EXAMPLES = [
  "foreign exchange and currency headwinds",
  "generative AI investment and risk",
  "data center capacity constraints",
];

export function ScreenPanel({ onRun }: { onRun?: (run: SessionRun) => void }) {
  const [query, setQuery] = useState("");
  const [issuers, setIssuers] = useState(6);
  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState(0);
  const [result, setResult] = useState<ThematicScanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [estimateMs, setEstimateMs] = useState(DEFAULT_SCAN_MS);

  useEffect(() => {
    if (!loading) return;
    // Advance the qualitative stage labels across the expected duration.
    const timer = window.setInterval(
      () => setStage((current) => Math.min(current + 1, SCAN_STAGES.length - 1)),
      Math.max(3000, estimateMs / SCAN_STAGES.length),
    );
    return () => window.clearInterval(timer);
  }, [loading, estimateMs]);

  async function run(theme: string) {
    if (!theme.trim() || loading) return;
    setStage(0);
    setLoading(true);
    setError(null);
    setResult(null);
    const startedAt = performance.now();
    try {
      const response = await runThematicScan(theme.trim(), issuers, 1);
      // Calibrate the next scan's progress bar to what this one actually took.
      const observed = performance.now() - startedAt;
      setEstimateMs((prev) =>
        Math.min(90_000, Math.max(6_000, Math.round(prev * 0.4 + observed * 0.6))),
      );
      setResult(response);
      const top = Math.max(
        0,
        ...response.issuers.map((issuer) => issuer.evidence[0]?.rerank_score ?? 0),
      );
      onRun?.({
        mode: "screen",
        latencyMs: response.latency_ms,
        grounded: response.issuer_count > 0,
        abstained: false,
        topScore: top,
        confidence: 0,
      });
    } catch (cause) {
      setResult(null);
      setError(cause instanceof Error ? cause.message : "The scan failed.");
    } finally {
      setLoading(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await run(query);
  }

  return (
    <div className="mode-panel">
      <div className="panel-intro">
        <p className="eyebrow">Cross-sectional scan</p>
        <h2>One theme, diversified across issuers</h2>
        <p className="panel-lede">
          Retrieve the strongest passage per company for a research theme, capped to one hit per
          issuer so a single filer cannot dominate the result set.
        </p>
      </div>

      <form className="screen-form" onSubmit={submit}>
        <div className="rf-query">
          <ScanSearch size={18} aria-hidden="true" />
          <input
            aria-label="Theme to scan"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="A theme to scan across the S&P 500…"
          />
          <button type="submit" disabled={loading}>
            {loading ? <LoaderCircle className="spin" size={16} /> : <ArrowRight size={16} />}
            {loading ? "Scanning" : "Scan"}
          </button>
        </div>
        <div className="screen-controls">
          <label className="rf-field rf-range">
            <span>Issuers: {issuers}</span>
            <input
              type="range"
              min={4}
              max={10}
              value={issuers}
              onChange={(event) => setIssuers(Number(event.target.value))}
            />
          </label>
          <div className="screen-examples">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => {
                  setQuery(example);
                  void run(example);
                }}
                disabled={loading}
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      </form>

      {loading && (
        <div className="loading-state" role="status">
          <LoaderCircle className="spin" size={24} />
          <div>
            <h3>Deep cross-sectional scan</h3>
            <p>{query}</p>
          </div>
          <ScanProgress estimateMs={estimateMs} />
          <ol aria-label="Scan stages">
            {SCAN_STAGES.map((label, index) => (
              <li
                key={label}
                className={index === stage ? "active" : index < stage ? "complete" : undefined}
              >
                {label}
              </li>
            ))}
          </ol>
        </div>
      )}

      {error && (
        <div className="notice error" role="alert">
          <CircleAlert size={19} />
          <div>
            <strong>Scan failed</strong>
            <p>{error}</p>
          </div>
        </div>
      )}

      {result && !loading && (
        <div className="screen-results">
          <div className="rr-summary">
            <span>
              <strong>{result.issuer_count}</strong> issuers
            </span>
            <span>{formatLatency(result.latency_ms)}</span>
          </div>
          <div className="issuer-grid">
            {result.issuers.map((issuer, index) => {
              const top = issuer.evidence[0];
              const meta = top?.metadata ?? {};
              return (
                <article key={issuer.ticker} className="issuer-card">
                  <header>
                    <span className="issuer-rank">{String(index + 1).padStart(2, "0")}</span>
                    <div>
                      <strong>{issuer.ticker}</strong>
                      <small>{issuer.company_name}</small>
                    </div>
                    <span className="issuer-score">{score(top?.rerank_score ?? null)}</span>
                  </header>
                  {top && <p className="issuer-quote">{top.text}</p>}
                  <footer>
                    <span>{metadataValue(meta.form_type, "Filing")}</span>
                    <span>{metadataValue(meta.section, "Unsectioned")}</span>
                    <span>{metadataValue(meta.filing_date, "")}</span>
                  </footer>
                </article>
              );
            })}
          </div>
        </div>
      )}

      {!result && !error && !loading && (
        <div className="empty-state compact">
          <ScanSearch size={26} />
          <h3>Scan a theme across the universe</h3>
          <p>Pick an example or enter your own; deep scans take ~30s.</p>
        </div>
      )}
    </div>
  );
}
