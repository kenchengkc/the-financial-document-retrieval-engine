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
  rankDelta,
}: {
  candidate: RetrievalCandidate;
  index: number;
  defaultOpen?: boolean;
  cited?: boolean;
  heat?: number;
  commonTicker?: string | null;
  commonSection?: string | null;
  rankDelta?: number | null;
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
        <span className="evidence-score">
          <RankDelta delta={rankDelta} />
          {score(candidate.rerank_score)} rerank
        </span>
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

/** Rank movement per chunk: hybrid-order rank minus displayed (rerank) rank.
 * Positive = the cross-encoder promoted the passage; negative = demoted. */
export function rankDeltas(candidates: RetrievalCandidate[]): Map<number, number> {
  const byHybrid = [...candidates].sort(
    (a, b) => (b.hybrid_score ?? 0) - (a.hybrid_score ?? 0),
  );
  const hybridRank = new Map(byHybrid.map((c, i) => [c.chunk_id, i]));
  const deltas = new Map<number, number>();
  candidates.forEach((candidate, displayedRank) => {
    const from = hybridRank.get(candidate.chunk_id);
    deltas.set(candidate.chunk_id, from === undefined ? 0 : from - displayedRank);
  });
  return deltas;
}

export function RankDelta({ delta }: { delta: number | null | undefined }) {
  if (delta === null || delta === undefined) return null;
  if (delta === 0) {
    return (
      <span className="rank-delta flat" title="Rerank kept the hybrid position">
        =
      </span>
    );
  }
  const up = delta > 0;
  return (
    <span
      className={`rank-delta ${up ? "up" : "down"}`}
      title={`Cross-encoder ${up ? "promoted" : "demoted"} this passage ${Math.abs(delta)} place${Math.abs(delta) === 1 ? "" : "s"} vs hybrid order`}
    >
      {up ? "▲" : "▼"}
      {Math.abs(delta)}
    </span>
  );
}

/** Set-level analysis of a ranked result list: score decay by rank against the
 * evidence gate, plus composition facts (issuers, sections, date span) and how
 * much the cross-encoder reshuffled the hybrid order. */
export function ResultAnalysis({
  candidates,
  gateThreshold = 0.4,
}: {
  candidates: RetrievalCandidate[];
  gateThreshold?: number;
}) {
  if (candidates.length === 0) return null;
  const scores = candidates.map((c) => c.rerank_score ?? 0);
  const top = Math.max(...scores);
  const med = median(scores);
  const scaleMax = Math.max(top, gateThreshold * 1.35, 0.0001);
  const issuers = new Set(
    candidates.map((c) => metadataValue(c.metadata.ticker, "?")),
  );
  const sections = new Map<string, number>();
  for (const c of candidates) {
    const s = metadataValue(c.metadata.section, "Unsectioned");
    sections.set(s, (sections.get(s) ?? 0) + 1);
  }
  const topSection = [...sections.entries()].sort((a, b) => b[1] - a[1])[0];
  const dates = candidates
    .map((c) => metadataValue(c.metadata.filing_date, ""))
    .filter(Boolean)
    .sort();
  const deltas = rankDeltas(candidates);
  const shuffled = candidates.filter((c) => (deltas.get(c.chunk_id) ?? 0) !== 0).length;
  const gatePct = Math.min(100, (gateThreshold / scaleMax) * 100);
  const cells: { k: string; v: string; title?: string }[] = [
    { k: "Top / median", v: `${top.toFixed(3)} / ${med.toFixed(3)}` },
    { k: "Issuers", v: String(issuers.size) },
    {
      k: "Top section",
      v: topSection ? `${topSection[0]}` : "N/A",
      title: topSection ? `${topSection[1]} of ${candidates.length} passages` : undefined,
    },
    {
      k: "Filing span",
      v: dates.length ? `${dates[0]} → ${dates[dates.length - 1]}` : "N/A",
    },
    {
      k: "Rerank moved",
      v: `${shuffled}/${candidates.length}`,
      title: "Passages whose position changed vs the hybrid-score order",
    },
  ];
  return (
    <div className="ranalysis" aria-label="Result-set analysis">
      <div className="ra-chart" role="img" aria-label="Rerank score by rank position">
        <span
          className="ra-gate"
          style={{ bottom: `${gatePct}%` }}
          data-label={`evidence gate ${gateThreshold.toFixed(2)}`}
        />
        {candidates.map((c, i) => {
          const value = c.rerank_score ?? 0;
          const passed = value >= gateThreshold;
          return (
            <span
              key={c.chunk_id}
              className={`ra-bar${passed ? "" : " below"}`}
              style={{ height: `${Math.max(3, (value / scaleMax) * 100)}%` }}
              title={`#${i + 1} ${metadataValue(c.metadata.ticker, "?")} · rerank ${value.toFixed(3)}${passed ? "" : " · below gate"}`}
            />
          );
        })}
      </div>
      <dl className="ra-cells">
        {cells.map((cell) => (
          <div key={cell.k} title={cell.title}>
            <dt>{cell.k}</dt>
            <dd>{cell.v}</dd>
          </div>
        ))}
      </dl>
    </div>
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
    { k: "No answer", v: String(abstained) },
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
