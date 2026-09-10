"use client";

import { ArrowRight, Download, Layers3, LoaderCircle, ShieldCheck } from "lucide-react";
import { FormEvent, useState } from "react";

import {
  downloadResearchPanel,
  fetchResearchPanel,
  type ResearchPanelOptions,
} from "@/lib/api";
import type { ResearchPanel } from "@/lib/types";

import { dateLabel, splitTickers, ToolError } from "./retrieve-research-shared";

const FORM_OPTIONS = ["10-K", "10-Q", "8-K"];

export function ResearchDatasetTool() {
  const [tickers, setTickers] = useState("");
  const [forms, setForms] = useState(["10-K", "10-Q"]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [asOf, setAsOf] = useState("");
  const [format, setFormat] = useState<"csv" | "json" | "parquet">("parquet");
  const [limit, setLimit] = useState(250);
  const [result, setResult] = useState<ResearchPanel | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function options(): ResearchPanelOptions {
    return {
      tickers: splitTickers(tickers),
      formTypes: forms,
      periodEndFrom: from || undefined,
      periodEndTo: to || undefined,
      asOf: asOf || undefined,
      includeAmendments: false,
      limit,
    };
  }

  function toggleForm(form: string) {
    setForms((current) => current.includes(form) ? current.filter((item) => item !== form) : [...current, form]);
  }

  async function build(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (loading || forms.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await fetchResearchPanel(options()));
    } catch (cause) {
      setResult(null);
      setError(cause instanceof Error ? cause.message : "The dataset preview failed.");
    } finally {
      setLoading(false);
    }
  }

  async function download() {
    if (downloading || !result) return;
    setDownloading(true);
    setError(null);
    try {
      await downloadResearchPanel(options(), format);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The dataset download failed.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <section className="retrieve-lab" aria-labelledby="research-dataset-title">
      <header className="lab-heading">
        <span className="lab-icon"><Layers3 size={17} aria-hidden="true" /></span>
        <div>
          <p className="eyebrow">Company-period research data</p>
          <h3 id="research-dataset-title">Build a research dataset</h3>
          <p>
            Create one row per filing with disclosure-change and fundamental features, filtered to
            information available by the cutoff date. Preview the rows, then download CSV, JSON,
            or Parquet.
          </p>
        </div>
      </header>

      <form className="lab-form panel-form" onSubmit={build}>
        <label>
          <span>Tickers (blank for all companies)</span>
          <input aria-label="Dataset tickers" value={tickers} onChange={(event) => setTickers(event.target.value)} placeholder="AAPL, MSFT" />
        </label>
        <label><span>Fiscal period from</span><input aria-label="Dataset fiscal period from" type="date" value={from} onChange={(event) => setFrom(event.target.value)} /></label>
        <label><span>Fiscal period to</span><input aria-label="Dataset fiscal period to" type="date" value={to} onChange={(event) => setTo(event.target.value)} /></label>
        <label><span>As-of date</span><input aria-label="Dataset as-of date" type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} /></label>
        <div className="lab-control">
          <span>Filing types</span>
          <div className="lab-chips">
            {FORM_OPTIONS.map((form) => <button key={form} type="button" className={forms.includes(form) ? "on" : undefined} onClick={() => toggleForm(form)}>{form}</button>)}
          </div>
        </div>
        <label><span>Export row limit</span><input aria-label="Dataset row limit" type="number" min={25} max={10000} step={25} value={limit} onChange={(event) => setLimit(Math.min(10000, Math.max(25, Number(event.target.value) || 25)))} /></label>
        <button className="lab-primary" type="submit" disabled={loading || forms.length === 0}>
          {loading ? <LoaderCircle className="spin" size={16} /> : <ArrowRight size={16} />}
          {loading ? "Building" : "Preview dataset"}
        </button>
      </form>

      {error && <ToolError message={error} />}
      {result && (
        <div className="panel-result">
          <div className="panel-manifest">
            <div><span>Rows</span><strong>{result.rows.length.toLocaleString()}</strong></div>
            <div><span>Feature version</span><strong>{result.feature_version}</strong></div>
            <div><span>Data snapshot</span><strong title={result.corpus_snapshot_id}>{result.corpus_snapshot_id.slice(0, 12)}</strong></div>
            <div className="manifest-gate"><ShieldCheck size={16} /><span>As-of data check</span><strong>Passed</strong></div>
            <label className="export-format"><span>Format</span><select aria-label="Dataset download format" value={format} onChange={(event) => setFormat(event.target.value as typeof format)}><option value="parquet">Parquet</option><option value="csv">CSV</option><option value="json">JSON</option></select></label>
            <button type="button" className="lab-download" onClick={download} disabled={downloading} title="Download research dataset">
              {downloading ? <LoaderCircle className="spin" size={16} /> : <Download size={16} />}
              {downloading ? "Preparing" : "Download"}
            </button>
          </div>
          <div className="lab-table-wrap">
            <table className="lab-table panel-table">
              <thead><tr><th>Company</th><th>Period</th><th>Filing</th><th className="num">Disclosure similarity</th><th className="num">Net risk passages</th><th className="num">Operating margin</th><th>Available</th></tr></thead>
              <tbody>
                {result.rows.slice(0, 8).map((row) => (
                  <tr key={row.accession_number}>
                    <td><strong>{row.ticker}</strong></td>
                    <td>{dateLabel(row.period_end)}</td>
                    <td>{row.form_type}</td>
                    <td className="num">{row.disclosure_similarity === null ? "N/A" : row.disclosure_similarity.toFixed(3)}</td>
                    <td className="num">{(row.risk_added_passages ?? 0) - (row.risk_removed_passages ?? 0)}</td>
                    <td className="num">{row.operating_margin === null ? "N/A" : `${(row.operating_margin * 100).toFixed(1)}%`}</td>
                    <td>{dateLabel(row.available_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.rows.length === 0 && <p className="lab-empty">No company-period rows matched these filters.</p>}
        </div>
      )}
    </section>
  );
}
