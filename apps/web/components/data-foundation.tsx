"use client";

import {
  Activity,
  Building2,
  ChevronDown,
  Database,
  Gauge,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fetchCompanies, fetchCoverage, fetchOperationsQuality } from "@/lib/api";
import type { Company, CoverageResponse, OperationsQuality } from "@/lib/types";

import { formatLatency, median, type SessionRun } from "./instruments";

type FoundationData = {
  companies: Company[];
  coverage: CoverageResponse | null;
  operations: OperationsQuality | null;
};

const EMPTY_DATA: FoundationData = {
  companies: [],
  coverage: null,
  operations: null,
};

function compactNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en", {
    notation: value >= 100_000 ? "compact" : "standard",
    maximumFractionDigits: 1,
  }).format(value);
}

function percent(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

function timeAgo(iso: string | null | undefined) {
  if (!iso) return "—";
  const elapsedMinutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000));
  if (elapsedMinutes < 60) return `${elapsedMinutes} min`;
  const elapsedHours = Math.round(elapsedMinutes / 60);
  if (elapsedHours < 48) return `${elapsedHours} h`;
  return `${Math.round(elapsedHours / 24)} d`;
}

function CoverageMeter({
  label,
  value,
}: {
  label: string;
  value: number | null | undefined;
}) {
  const width = value === null || value === undefined ? 0 : Math.max(0, Math.min(1, value)) * 100;
  const tone = value !== null && value !== undefined && value >= 0.99 ? "good" : "warn";

  return (
    <div className="foundation-meter">
      <span>{label}</span>
      <span className="foundation-track" aria-hidden="true">
        <span className={tone} style={{ width: `${width}%` }} />
      </span>
      <code>{percent(value)}</code>
    </div>
  );
}

export function DataFoundation({ runs }: { runs: SessionRun[] }) {
  const [open, setOpen] = useState(true);
  const [data, setData] = useState<FoundationData>(EMPTY_DATA);

  useEffect(() => {
    let active = true;

    void (async () => {
      const [coverage, companies, operations] = await Promise.all([
        fetchCoverage(),
        fetchCompanies().then((response) => response.companies).catch(() => []),
        fetchOperationsQuality().catch(() => null),
      ]);
      if (active) setData({ coverage, companies, operations });
    })();

    return () => {
      active = false;
    };
  }, []);

  const topCompanies = useMemo(
    () => [...data.companies].sort((left, right) => right.chunk_count - left.chunk_count).slice(0, 5),
    [data.companies],
  );
  const maxChunks = Math.max(1, ...topCompanies.map((company) => company.chunk_count));
  const nyse = data.companies.filter((company) => company.exchange?.toUpperCase() === "NYSE").length;
  const nasdaq = data.companies.filter((company) =>
    company.exchange?.toUpperCase().includes("NASDAQ"),
  ).length;
  const operations = data.operations;
  const issuerCount = data.coverage?.indexed_count ?? operations?.company_count;
  const filingCount = data.coverage?.document_count ?? operations?.document_count;
  const chunkCount = data.coverage?.chunk_count ?? operations?.chunk_count;
  const answerP50 = runs.length ? formatLatency(median(runs.map((run) => run.latencyMs))) : "—";
  const strip = [
    { label: "issuers indexed", value: compactNumber(issuerCount) },
    { label: "filings", value: compactNumber(filingCount) },
    { label: "chunks", value: compactNumber(chunkCount) },
    { label: "embedding coverage", value: percent(operations?.embedding_coverage) },
    { label: "index freshness", value: timeAgo(operations?.latest_ingestion_completed_at) },
    { label: "answer p50", value: answerP50 },
  ];
  const operationMeters = [
    { label: "Document to chunk", value: operations?.document_chunk_coverage },
    { label: "Embedding coverage", value: operations?.embedding_coverage },
    { label: "Freshness ratio", value: operations?.freshness_ratio },
    { label: "Ingestion success", value: operations?.recent_ingestion_success_rate },
  ];

  return (
    <section className={`data-foundation${open ? " open" : ""}`} aria-label="Data foundation">
      <button
        type="button"
        className="foundation-bar"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-controls="foundation-details"
      >
        <span className="foundation-title">
          <span className="foundation-live" aria-hidden="true" />
          Data foundation
        </span>
        <span className="foundation-stats">
          {strip.map((item) => (
            <span className="foundation-stat" key={item.label}>
              <strong>{item.value}</strong>
              <small>{item.label}</small>
            </span>
          ))}
        </span>
        <span className="foundation-inspect">
          Inspect <ChevronDown size={14} aria-hidden="true" />
        </span>
      </button>

      {open && (
        <div className="foundation-details" id="foundation-details">
          <section className="foundation-column">
            <h3>
              <Building2 size={16} aria-hidden="true" /> Universe
            </h3>
            <p>
              Indexed SEC filing coverage, resolved to issuer metadata and searchable chunks.
            </p>
            <div className="foundation-split">
              <span>
                <strong>{nyse || "—"}</strong> NYSE
              </span>
              <span>
                <strong>{nasdaq || "—"}</strong> Nasdaq
              </span>
              <span>
                <strong>{data.coverage?.sp500_indexed_count ?? "—"}</strong> S&amp;P 500
              </span>
            </div>
            <div className="foundation-company-list" role="list" aria-label="Largest filing footprints">
              {topCompanies.map((company) => (
                <div className="foundation-company" role="listitem" key={company.ticker}>
                  <span className="foundation-ticker">{company.ticker}</span>
                  <span className="foundation-track" aria-hidden="true">
                    <span style={{ width: `${(company.chunk_count / maxChunks) * 100}%` }} />
                  </span>
                  <code>{compactNumber(company.chunk_count)} chunks</code>
                </div>
              ))}
              {!topCompanies.length && (
                <p className="foundation-unavailable">
                  <Database size={14} aria-hidden="true" /> Connect the data service to inspect issuer coverage.
                </p>
              )}
            </div>
          </section>

          <section className="foundation-column">
            <h3>
              <Gauge size={16} aria-hidden="true" /> Operations
            </h3>
            <p>Every filing is checked for retrieval completeness before it enters the research corpus.</p>
            <div className="foundation-meters">
              {operationMeters.map((meter) => (
                <CoverageMeter key={meter.label} {...meter} />
              ))}
            </div>
            <div className="foundation-ops">
              <span>
                <Activity size={13} aria-hidden="true" />
                <strong>{timeAgo(operations?.latest_ingestion_completed_at)}</strong> last ingest
              </span>
              <span>
                <ShieldCheck size={13} aria-hidden="true" />
                <strong>{operations?.documents_without_chunks ?? "—"}</strong> unchunked docs
              </span>
              <span>
                <Database size={13} aria-hidden="true" />
                <strong>{compactNumber(operations?.chunks_without_embeddings)}</strong> missing embeddings
              </span>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
