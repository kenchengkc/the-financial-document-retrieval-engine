"use client";

import { ChevronDown } from "lucide-react";
import type { CSSProperties } from "react";

import type { AnswerResponse, RetrievalCandidate } from "@/lib/types";

export function score(value: number | null) {
  return value === null ? "n/a" : value.toFixed(3);
}

export function metadataValue(value: unknown, fallback: string) {
  return typeof value === "string" && value.trim() ? value : fallback;
}

export function formatLatency(latencyMs: number) {
  return latencyMs < 1000 ? `${latencyMs} ms` : `${(latencyMs / 1000).toFixed(1)} s`;
}

export function traceCount(trace: AnswerResponse["trace"], node: string): number | null {
  const step = trace.find((entry) => entry.node === node);
  const value = step?.details?.count;
  return typeof value === "number" ? value : null;
}

export function resolvedScope(trace: AnswerResponse["trace"]) {
  const step = trace.find((entry) => entry.node === "preprocess_query");
  const filters = (step?.details?.filters ?? {}) as Record<string, unknown>;
  const tickers = Array.isArray(filters.tickers) ? (filters.tickers as string[]) : [];
  const forms = Array.isArray(filters.form_types) ? (filters.form_types as string[]) : [];
  const asOf = typeof filters.as_of === "string" ? filters.as_of : null;
  return { tickers, forms, asOf };
}

export function median(values: number[]) {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((left, right) => left - right);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

export type SessionRun = {
  mode: string;
  latencyMs: number;
  grounded: boolean;
  abstained: boolean;
  topScore: number;
  confidence: number;
};

export function ScoreGauge({
  label,
  hint,
  value,
  accent = false,
}: {
  label: string;
  hint: string;
  value: number | null;
  accent?: boolean;
}) {
  const pct = value === null ? 0 : Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className={`gauge${accent ? " accent" : ""}`}>
      <span className="gauge-head">
        <span className="gauge-label">{label}</span>
        <span className="gauge-hint">{hint}</span>
      </span>
      <span className="gauge-track" aria-hidden="true">
        <span className="gauge-fill" style={{ width: `${pct}%` }} />
      </span>
      <span className="gauge-value">{score(value)}</span>
    </div>
  );
}

export function ScoreRow({ candidate }: { candidate: RetrievalCandidate }) {
  return (
    <div className="scores">
      <ScoreGauge label="Dense" hint="cosine" value={candidate.dense_score} />
      <ScoreGauge label="Sparse" hint="lexical" value={candidate.sparse_score} />
      <ScoreGauge label="Hybrid" hint="fused" value={candidate.hybrid_score} />
      <ScoreGauge label="Rerank" hint="cross-enc" value={candidate.rerank_score} accent />
    </div>
  );
}

export function EvidenceCard({
  candidate,
  index,
  defaultOpen,
  cited,
  heat,
  commonTicker,
  commonSection,
}: {
  candidate: RetrievalCandidate;
  index: number;
  defaultOpen?: boolean;
  cited?: boolean;
  heat?: number;
  commonTicker?: string | null;
  commonSection?: string | null;
}) {
  const metadata = candidate.metadata;
  const ticker = metadataValue(metadata.ticker, "Document");
  const formType = metadataValue(metadata.form_type, "Filing");
  const section = metadataValue(metadata.section, "Unsectioned");
  const filingDate = metadataValue(metadata.filing_date, "Date unavailable");
  const tickerDim = commonTicker != null && ticker === commonTicker;
  const sectionDim = commonSection != null && section === commonSection;

  return (
    <details className={`evidence${cited ? " cited" : ""}`} open={defaultOpen ? true : undefined}>
      <summary>
        <span className="evidence-rank">{String(index + 1).padStart(2, "0")}</span>
        <span className="evidence-source">
          <span className="evidence-src-top">
            <strong className={tickerDim ? "dim" : undefined}>{ticker}</strong>
            {cited ? <span className="evidence-cited">Cited</span> : null}
          </span>
          <span>
            {formType} · {filingDate}
          </span>
        </span>
        <span className={`evidence-section${sectionDim ? " dim" : ""}`}>{section}</span>
        <span className="evidence-score">{score(candidate.rerank_score)} rerank</span>
        <ChevronDown size={16} aria-hidden="true" />
        <span className="evidence-heat" aria-hidden="true">
          <span style={{ width: `${Math.round(Math.max(0, Math.min(1, heat ?? 0)) * 100)}%` }} />
        </span>
      </summary>
      <div className="evidence-body">
        <p>{candidate.text}</p>
        <ScoreRow candidate={candidate} />
      </div>
    </details>
  );
}

export function ConfidenceRing({ value }: { value: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div
      className="conf-ring"
      style={{ "--p": pct } as CSSProperties}
      role="img"
      aria-label={`${pct} percent retrieval confidence`}
    >
      <span className="conf-num">{pct}</span>
      <span className="conf-unit">%</span>
    </div>
  );
}

export function RetrievalFunnel({
  retrieved,
  reranked,
  gatePassed,
  cited,
}: {
  retrieved: number;
  reranked: number;
  gatePassed: boolean;
  cited: number;
}) {
  const max = Math.max(retrieved, reranked, cited, 1);
  const stages: { label: string; sub: string; count: number; bar: number; tone?: string }[] = [
    { label: "Retrieved", sub: "hybrid candidates", count: retrieved, bar: retrieved },
    { label: "Reranked", sub: "cross-encoder kept", count: reranked, bar: reranked },
    {
      label: gatePassed ? "Gate passed" : "Gate held",
      sub: "evidence threshold",
      count: gatePassed ? reranked : 0,
      bar: gatePassed ? reranked : 0,
      tone: gatePassed ? undefined : "hold",
    },
    { label: "Cited", sub: "citation-verified", count: cited, bar: cited, tone: "cited" },
  ];
  return (
    <ol className="funnel" aria-label="Retrieval pipeline">
      {stages.map((stage) => (
        <li key={stage.label} className={stage.tone ? `fn-${stage.tone}` : undefined}>
          <span className="fn-label">
            {stage.label}
            <small>{stage.sub}</small>
          </span>
          <span className="fn-track" aria-hidden="true">
            <span className="fn-fill" style={{ width: `${(stage.bar / max) * 100}%` }} />
          </span>
          <span className="fn-count">{stage.count}</span>
        </li>
      ))}
    </ol>
  );
}

export function SessionTelemetry({ runs }: { runs: SessionRun[] }) {
  const grounded = runs.filter((run) => run.grounded).length;
  const abstained = runs.filter((run) => run.abstained).length;
  const groundedPct = runs.length ? Math.round((grounded / runs.length) * 100) : 0;
  const medianLatency = Math.round(median(runs.map((run) => run.latencyMs)));
  const scored = runs.filter((run) => run.topScore > 0);
  const avgTop = scored.length
    ? scored.reduce((sum, run) => sum + run.topScore, 0) / scored.length
    : 0;
  const cells = [
    { k: "Queries", v: String(runs.length) },
    { k: "Grounded", v: `${groundedPct}%` },
    { k: "Abstained", v: String(abstained) },
    { k: "Median latency", v: formatLatency(medianLatency) },
    { k: "Avg top rerank", v: avgTop.toFixed(3) },
  ];
  return (
    <div className="telemetry" aria-label="Session telemetry">
      <span className="tm-title">
        <span className="tm-dot" aria-hidden="true" />
        Session telemetry
      </span>
      <dl className="tm-cells">
        {cells.map((cell) => (
          <div key={cell.k}>
            <dt>{cell.k}</dt>
            <dd>{cell.v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
