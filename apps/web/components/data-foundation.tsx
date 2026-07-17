"use client";

import {
  Activity,
  Building2,
  ChevronDown,
  CircleAlert,
  Database,
  Gauge,
  LoaderCircle,
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

type FoundationSource = keyof FoundationData;
type SourceStatus = "loading" | "ready" | "error";
type SourceStatuses = Record<FoundationSource, SourceStatus>;

const EMPTY_DATA: FoundationData = {
  companies: [],
  coverage: null,
  operations: null,
};

const INITIAL_SOURCE_STATUSES: SourceStatuses = {
  companies: "loading",
  coverage: "loading",
  operations: "loading",
};

const FOUNDATION_CACHE_KEY = "fdre.foundation.v1";
const FOUNDATION_CACHE_TTL_MS = 6 * 60 * 60 * 1000;

type FoundationCache = {
  savedAt: number;
  data: FoundationData;
};

function readFoundationCache(): FoundationCache | null {
  try {
    const raw = window.localStorage.getItem(FOUNDATION_CACHE_KEY);
    if (!raw) return null;
    const cached = JSON.parse(raw) as FoundationCache;
    if (
      !Number.isFinite(cached.savedAt) ||
      Date.now() - cached.savedAt > FOUNDATION_CACHE_TTL_MS ||
      !cached.data ||
      !Array.isArray(cached.data.companies)
    ) {
      window.localStorage.removeItem(FOUNDATION_CACHE_KEY);
      return null;
    }
    return cached;
  } catch {
    return null;
  }
}

function writeFoundationCache(data: FoundationData) {
  try {
    window.localStorage.setItem(
      FOUNDATION_CACHE_KEY,
      JSON.stringify({ savedAt: Date.now(), data } satisfies FoundationCache),
    );
  } catch {
    // Storage can be disabled; live requests remain the source of truth.
  }
}

function compactNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return "Unavailable";
  return new Intl.NumberFormat("en", {
    notation: value >= 100_000 ? "compact" : "standard",
    maximumFractionDigits: 1,
  }).format(value);
}

function percent(value: number | null | undefined) {
  return value === null || value === undefined ? "Unavailable" : `${(value * 100).toFixed(1)}%`;
}

function timeAgo(iso: string | null | undefined) {
  if (!iso) return "Unavailable";
  const elapsedMinutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000));
  if (elapsedMinutes < 60) return `${elapsedMinutes} min`;
  const elapsedHours = Math.round(elapsedMinutes / 60);
  if (elapsedHours < 48) return `${elapsedHours} h`;
  return `${Math.round(elapsedHours / 24)} d`;
}

function CoverageMeter({
  label,
  value,
  loading,
}: {
  label: string;
  value: number | null | undefined;
  loading: boolean;
}) {
  const width = loading
    ? 28
    : value === null || value === undefined
      ? 0
      : Math.max(0, Math.min(1, value)) * 100;
  const tone = value !== null && value !== undefined && value >= 0.99 ? "good" : "warn";

  return (
    <div className={`foundation-meter${loading ? " loading" : ""}`}>
      <span>{label}</span>
      <span className="foundation-track" aria-hidden="true">
        <span className={loading ? "loading" : tone} style={{ width: `${width}%` }} />
      </span>
      <code>{loading ? "Loading" : percent(value)}</code>
    </div>
  );
}

export function DataFoundation({ runs }: { runs: SessionRun[] }) {
  const [open, setOpen] = useState(true);
  const [data, setData] = useState<FoundationData>(EMPTY_DATA);
  const [sourceStatuses, setSourceStatuses] =
    useState<SourceStatuses>(INITIAL_SOURCE_STATUSES);
  const [cacheLoaded, setCacheLoaded] = useState(false);

  useEffect(() => {
    let active = true;
    const retryWaits = new Map<number, () => void>();
    const cached = readFoundationCache();
    if (cached) {
      const restoreTimer = window.setTimeout(() => {
        retryWaits.delete(restoreTimer);
        if (!active) return;
        setData(cached.data);
        setCacheLoaded(true);
      }, 0);
      retryWaits.set(restoreTimer, () => undefined);
    }

    const waitForRetry = (delayMs: number) =>
      new Promise<void>((resolve) => {
        const timer = window.setTimeout(() => {
          retryWaits.delete(timer);
          resolve();
        }, delayMs);
        retryWaits.set(timer, resolve);
      });

    async function retryRequest<T>(request: () => Promise<T>): Promise<T> {
      let lastError: unknown = new Error("Foundation request failed.");
      for (let attempt = 0; attempt < 3; attempt += 1) {
        if (!active) throw new Error("Foundation request cancelled.");
        try {
          return await request();
        } catch (error) {
          lastError = error;
          if (attempt < 2) await waitForRetry(attempt === 0 ? 700 : 1_500);
        }
      }
      throw lastError;
    }

    async function loadSource<T>(
      source: FoundationSource,
      request: () => Promise<T>,
      apply: (current: FoundationData, value: T) => FoundationData,
    ) {
      try {
        const value = await retryRequest(request);
        if (!active) return;
        setData((current) => apply(current, value));
        setSourceStatuses((current) => ({ ...current, [source]: "ready" }));
      } catch {
        if (active) {
          setSourceStatuses((current) => ({ ...current, [source]: "error" }));
        }
      }
    }

    const coverageRequest = loadSource(
      "coverage",
      async () => {
        const coverage = await fetchCoverage();
        if (!coverage) throw new Error("Coverage is unavailable.");
        return coverage;
      },
      (current, coverage) => ({ ...current, coverage }),
    );
    void loadSource(
      "companies",
      fetchCompanies,
      (current, response) => ({ ...current, companies: response.companies }),
    );
    void coverageRequest.then(() => {
      if (!active) return;
      void loadSource(
        "operations",
        fetchOperationsQuality,
        (current, operations) => ({ ...current, operations }),
      );
    });

    return () => {
      active = false;
      for (const [timer, resolve] of retryWaits) {
        window.clearTimeout(timer);
        resolve();
      }
      retryWaits.clear();
    };
  }, []);

  const foundationReady = Object.values(sourceStatuses).every((status) => status === "ready");
  useEffect(() => {
    if (foundationReady) writeFoundationCache(data);
  }, [data, foundationReady]);

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
  const coverageLoading = sourceStatuses.coverage === "loading" && !data.coverage;
  const companiesLoading = sourceStatuses.companies === "loading" && !data.companies.length;
  const operationsLoading = sourceStatuses.operations === "loading" && !operations;
  const corpusLoading = issuerCount === undefined && (coverageLoading || operationsLoading);
  const answerP50 = runs.length ? formatLatency(median(runs.map((run) => run.latencyMs))) : "No runs";
  const strip = [
    { label: "issuers indexed", value: compactNumber(issuerCount), loading: corpusLoading },
    { label: "filings", value: compactNumber(filingCount), loading: corpusLoading },
    { label: "chunks", value: compactNumber(chunkCount), loading: corpusLoading },
    {
      label: "embedding coverage",
      value: percent(operations?.embedding_coverage),
      loading: operationsLoading,
    },
    {
      label: "index freshness",
      value: timeAgo(operations?.latest_ingestion_completed_at),
      loading: operationsLoading,
    },
    { label: "session answer p50", value: answerP50, loading: false },
  ];
  const operationMeters = [
    { label: "Document to chunk", value: operations?.document_chunk_coverage },
    { label: "Embedding coverage", value: operations?.embedding_coverage },
    { label: "Freshness ratio", value: operations?.freshness_ratio },
    { label: "Ingestion success", value: operations?.recent_ingestion_success_rate },
  ];
  const pendingSources = Object.values(sourceStatuses).filter((status) => status === "loading").length;
  const failedSources = Object.values(sourceStatuses).filter((status) => status === "error").length;
  const noData = !data.coverage && !data.companies.length && !data.operations;
  const unavailable = pendingSources === 0 && noData;
  const refreshDelayed = failedSources > 0 && !unavailable;

  return (
    <section
      className={`data-foundation${open ? " open" : ""}${unavailable ? " unavailable" : ""}`}
      aria-label="Data foundation"
      aria-busy={pendingSources > 0}
    >
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
              <strong
                className={item.loading || item.value === "Unavailable" ? "loading" : undefined}
              >
                {item.loading ? "Loading" : item.value}
              </strong>
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
          {(unavailable || refreshDelayed) && (
            <div className="foundation-service-error" role="status">
              <CircleAlert size={16} aria-hidden="true" />
              <span>
                <strong>
                  {unavailable ? "Live data service unavailable." : "Live refresh delayed."}
                </strong>{" "}
                {cacheLoaded
                  ? "Showing the last verified metrics where available."
                  : "Some corpus metrics could not be loaded."}
              </span>
            </div>
          )}
          <section className="foundation-column">
            <h3>
              <Building2 size={16} aria-hidden="true" /> Universe
            </h3>
            <p>
              Indexed SEC filing coverage, resolved to issuer metadata and searchable chunks.
            </p>
            <div className="foundation-split">
              <span>
                <strong>
                  {companiesLoading ? "Loading" : data.companies.length ? nyse : "Unavailable"}
                </strong>{" "}
                NYSE
              </span>
              <span>
                <strong>
                  {companiesLoading ? "Loading" : data.companies.length ? nasdaq : "Unavailable"}
                </strong>{" "}
                Nasdaq
              </span>
              <span>
                <strong>
                  {coverageLoading
                    ? "Loading"
                    : (data.coverage?.sp500_indexed_count ?? "Unavailable")}
                </strong>{" "}
                S&amp;P 500
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
              {companiesLoading && (
                <p className="foundation-unavailable loading" role="status">
                  <LoaderCircle className="spin" size={14} aria-hidden="true" /> Loading issuer coverage
                </p>
              )}
              {!topCompanies.length && !companiesLoading && (
                <p className="foundation-unavailable">
                  <Database size={14} aria-hidden="true" /> Issuer coverage is temporarily unavailable.
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
                <CoverageMeter key={meter.label} {...meter} loading={operationsLoading} />
              ))}
            </div>
            <div className="foundation-ops">
              <span>
                <Activity size={13} aria-hidden="true" />
                <strong>
                  {operationsLoading
                    ? "Loading"
                    : timeAgo(operations?.latest_ingestion_completed_at)}
                </strong>{" "}
                last ingest
              </span>
              <span>
                <ShieldCheck size={13} aria-hidden="true" />
                <strong>
                  {operationsLoading
                    ? "Loading"
                    : (operations?.documents_without_chunks ?? "Unavailable")}
                </strong>{" "}
                unchunked docs
              </span>
              <span>
                <Database size={13} aria-hidden="true" />
                <strong>
                  {operationsLoading
                    ? "Loading"
                    : compactNumber(operations?.chunks_without_embeddings)}
                </strong>{" "}
                missing embeddings
              </span>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
