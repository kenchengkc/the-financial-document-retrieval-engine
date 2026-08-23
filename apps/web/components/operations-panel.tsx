"use client";

import {
  Activity,
  CircleAlert,
  Database,
  GaugeCircle,
  LoaderCircle,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useState } from "react";

import { fetchOperationsQuality } from "@/lib/api";
import type { OperationsQuality } from "@/lib/types";

import { ScanProgress } from "./scan-progress";

function pct(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

function timeAgo(iso: string | null) {
  if (!iso) return "unknown";
  const then = new Date(iso).getTime();
  const hours = (Date.now() - then) / 3_600_000;
  if (hours < 1) return `${Math.round(hours * 60)} min ago`;
  if (hours < 48) return `${Math.round(hours)} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

function CoverageBar({ label, value }: { label: string; value: number }) {
  const tone = value >= 0.99 ? "good" : value >= 0.95 ? "warn" : "bad";
  return (
    <div className="cov-bar">
      <span className="cov-head">
        <span>{label}</span>
        <strong>{pct(value)}</strong>
      </span>
      <span className="cov-track" aria-hidden="true">
        <span className={`cov-fill ${tone}`} style={{ width: `${value * 100}%` }} />
      </span>
    </div>
  );
}

export function OperationsPanel() {
  const [report, setReport] = useState<OperationsQuality | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const response = await fetchOperationsQuality();
        if (active) setReport(response);
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : "Failed to load report.");
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  if (error) {
    return (
      <div className="mode-panel">
        <div className="notice error" role="alert">
          <CircleAlert size={19} />
          <div>
            <strong>Could not load the data status report</strong>
            <p>{error}</p>
          </div>
        </div>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="mode-panel">
        <div className="loading-state" role="status">
          <LoaderCircle className="spin" size={24} />
          <div>
            <h3>Reading the data status report</h3>
            <p>Checking the live filing data…</p>
          </div>
          <ScanProgress
            estimateMs={12_000}
            stages={[
              "Connecting to the data service",
              "Checking filing data",
              "Calculating coverage",
            ]}
          />
        </div>
      </div>
    );
  }

  const counts = [
    { k: "Companies", v: report.company_count.toLocaleString() },
    { k: "Filings", v: report.document_count.toLocaleString() },
    { k: "Passages", v: report.chunk_count.toLocaleString() },
    { k: "Vectors", v: report.embedding_count.toLocaleString() },
  ];

  const audits = [
    { k: "Filings without passages", v: report.documents_without_chunks, bad: report.documents_without_chunks > 0 },
    { k: "Passages without vectors", v: report.chunks_without_embeddings.toLocaleString(), bad: report.chunks_without_embeddings > 0 },
    { k: "Duplicate accession groups", v: report.duplicate_accession_groups, bad: report.duplicate_accession_groups > 0 },
    { k: "Facts without documents", v: report.facts_without_documents, bad: report.facts_without_documents > 0 },
  ];

  return (
    <div className="mode-panel">
      <div className="panel-intro">
        <p className="eyebrow">Data status</p>
        <h2>
          Live filing data, checked on{" "}
          <span className="accent">{new Date(report.generated_at).toISOString().slice(0, 10)}</span>
        </h2>
        <p className="panel-lede">
          Read from the production database: filing coverage, recent updates, and data checks.
          Last update {timeAgo(report.latest_ingestion_completed_at)}.
        </p>
      </div>

      <dl className="ops-counts">
        {counts.map((cell) => (
          <div key={cell.k}>
            <dt>{cell.k}</dt>
            <dd>{cell.v}</dd>
          </div>
        ))}
      </dl>

      <div className="ops-grid">
        <section className="ops-card">
          <div className="ops-card-title">
            <GaugeCircle size={16} aria-hidden="true" />
            <h3>Coverage and updates</h3>
          </div>
          <CoverageBar label="Filings split into passages" value={report.document_chunk_coverage} />
          <CoverageBar label="Passages with vectors" value={report.embedding_coverage} />
          <CoverageBar label="Recent filing coverage" value={report.freshness_ratio} />
          <CoverageBar label="Successful recent updates" value={report.recent_ingestion_success_rate} />
        </section>

        <section className="ops-card">
          <div className="ops-card-title">
            <ShieldCheck size={16} aria-hidden="true" />
            <h3>Data checks</h3>
          </div>
          <dl className="ops-audit">
            {audits.map((row) => (
              <div key={row.k}>
                <dt>{row.k}</dt>
                <dd className={row.bad ? "warn" : "ok"}>{row.v}</dd>
              </div>
            ))}
          </dl>
          <p className="ops-note">
            <Database size={12} aria-hidden="true" />
            Update window: {report.stale_after_days} days
          </p>
        </section>

        <section className="ops-card ops-watch">
          <div className="ops-card-title">
            <Activity size={16} aria-hidden="true" />
            <h3>Watchlist</h3>
          </div>
          <div className="ops-watch-block">
            <span className="ops-watch-label">Companies needing updates ({report.stale_tickers.length})</span>
            <div className="ops-tags">
              {report.stale_tickers.length ? (
                report.stale_tickers.map((ticker) => (
                  <span key={ticker} className="ops-tag">
                    {ticker}
                  </span>
                ))
              ) : (
                <span className="ops-clear">None</span>
              )}
            </div>
          </div>
          <div className="ops-watch-block">
            <span className="ops-watch-label">
              Missing expected filings ({report.missing_expected_filings.length})
            </span>
            <div className="ops-tags">
              {report.missing_expected_filings.length ? (
                report.missing_expected_filings.map((item) => (
                  <span key={item} className="ops-tag">
                    {item}
                  </span>
                ))
              ) : (
                <span className="ops-clear">None</span>
              )}
            </div>
          </div>
          {report.unchunked_documents?.length ? (
            <div className="ops-watch-block">
              <span className="ops-watch-label">
                Filings without passages ({report.unchunked_documents.length})
              </span>
              <div className="ops-tags">
                {report.unchunked_documents.map((item) => (
                  <span key={item.document_id} className="ops-tag" title={item.reason}>
                    {item.ticker}:{item.form_type}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
