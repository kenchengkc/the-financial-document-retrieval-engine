"use client";

import { Building2, CircleAlert, LoaderCircle, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fetchCompanies } from "@/lib/api";
import type { Company } from "@/lib/types";

import { ScanProgress } from "./scan-progress";

type SortKey = "chunk_count" | "document_count" | "ticker";

export function UniversePanel() {
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<SortKey>("chunk_count");

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const response = await fetchCompanies();
        if (active) setCompanies(response.companies);
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : "Failed to load companies.");
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const stats = useMemo(() => {
    if (!companies) return null;
    const nyse = companies.filter((company) => company.exchange === "NYSE").length;
    const nasdaq = companies.filter((company) => company.exchange === "Nasdaq").length;
    const docs = companies.reduce((sum, company) => sum + company.document_count, 0);
    const chunks = companies.reduce((sum, company) => sum + company.chunk_count, 0);
    return { count: companies.length, nyse, nasdaq, docs, chunks };
  }, [companies]);

  const rows = useMemo(() => {
    if (!companies) return [];
    const needle = filter.trim().toLowerCase();
    const filtered = needle
      ? companies.filter(
          (company) =>
            company.ticker.toLowerCase().includes(needle) ||
            company.name.toLowerCase().includes(needle),
        )
      : companies;
    const sorted = [...filtered].sort((left, right) => {
      if (sort === "ticker") return left.ticker.localeCompare(right.ticker);
      return right[sort] - left[sort];
    });
    return sorted;
  }, [companies, filter, sort]);

  if (error) {
    return (
      <div className="mode-panel">
        <div className="notice error" role="alert">
          <CircleAlert size={19} />
          <div>
            <strong>Could not load the universe</strong>
            <p>{error}</p>
          </div>
        </div>
      </div>
    );
  }

  if (!companies || !stats) {
    return (
      <div className="mode-panel">
        <div className="loading-state" role="status">
          <LoaderCircle className="spin" size={24} />
          <div>
            <h3>Loading the indexed universe</h3>
            <p>Reading company coverage from production…</p>
          </div>
          <ScanProgress
            estimateMs={8_000}
            stages={[
              "Connecting to the data service",
              "Loading issuer coverage",
              "Computing filing footprints",
            ]}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="mode-panel">
      <div className="panel-intro">
        <p className="eyebrow">Coverage universe</p>
        <h2>Every indexed issuer, with its filing footprint</h2>
        <p className="panel-lede">
          The current S&amp;P 500 constituent set, each name resolved to its CIK and indexed filings.
          The list is survivorship-biased by construction.
        </p>
      </div>

      <dl className="universe-stats">
        <div>
          <dt>Indexed issuers</dt>
          <dd>{stats.count}</dd>
        </div>
        <div>
          <dt>NYSE / Nasdaq</dt>
          <dd>
            {stats.nyse} / {stats.nasdaq}
          </dd>
        </div>
        <div>
          <dt>Filings</dt>
          <dd>{stats.docs.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Indexed chunks</dt>
          <dd>{stats.chunks.toLocaleString()}</dd>
        </div>
      </dl>

      <div className="universe-controls">
        <div className="universe-search">
          <Search size={16} aria-hidden="true" />
          <input
            aria-label="Filter companies"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter by ticker or name…"
          />
        </div>
        <div className="universe-sort">
          {(
            [
              ["chunk_count", "Chunks"],
              ["document_count", "Filings"],
              ["ticker", "Ticker"],
            ] as [SortKey, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={sort === key ? "on" : undefined}
              onClick={() => setSort(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="universe-table" role="table" aria-label="Indexed companies">
        <div className="ut-head" role="row">
          <span role="columnheader">Ticker</span>
          <span role="columnheader">Company</span>
          <span role="columnheader">Exch.</span>
          <span role="columnheader">Filings</span>
          <span role="columnheader">Chunks</span>
        </div>
        <div className="ut-body">
          {rows.slice(0, 120).map((company) => (
            <div className="ut-row" role="row" key={company.ticker}>
              <span role="cell" className="ut-ticker">
                {company.ticker}
              </span>
              <span role="cell" className="ut-name">
                {company.name}
              </span>
              <span role="cell" className="ut-exch">
                {company.exchange ?? "N/A"}
              </span>
              <span role="cell" className="ut-num">
                {company.document_count}
              </span>
              <span role="cell" className="ut-num">
                {company.chunk_count.toLocaleString()}
              </span>
            </div>
          ))}
        </div>
        <p className="ut-foot">
          <Building2 size={12} aria-hidden="true" />
          {rows.length > 120
            ? `Showing top 120 of ${rows.length.toLocaleString()} matching issuers. Refine the filter to narrow.`
            : `${rows.length.toLocaleString()} matching issuers`}
        </p>
      </div>
    </div>
  );
}
