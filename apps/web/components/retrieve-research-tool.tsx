"use client";

import {
  ArrowRight,
  Braces,
  CheckCircle2,
  CircleAlert,
  Download,
  FileDiff,
  Layers3,
  LoaderCircle,
  ShieldCheck,
} from "lucide-react";
import { FormEvent, useState } from "react";

import {
  downloadResearchPanel,
  fetchFilingDifference,
  fetchFinancialFacts,
  fetchResearchPanel,
  type ResearchPanelOptions,
} from "@/lib/api";
import type {
  CanonicalMetric,
  FilingDifference,
  FinancialFactsResponse,
  ResearchPanel,
} from "@/lib/types";

type ResearchTool = "delta" | "facts" | "panel";

const METRICS: Array<{ value: CanonicalMetric; label: string }> = [
  { value: "revenue", label: "Revenue" },
  { value: "operating_income", label: "Operating income" },
  { value: "net_income", label: "Net income" },
  { value: "eps", label: "Earnings per share" },
  { value: "cash", label: "Cash" },
  { value: "debt", label: "Debt" },
  { value: "shares", label: "Shares" },
  { value: "capex", label: "Capital expenditure" },
  { value: "operating_cash_flow", label: "Operating cash flow" },
];

const FORM_OPTIONS = ["10-K", "10-Q", "8-K"];

function splitTickers(value: string) {
  return value
    .split(/[\s,]+/)
    .map((ticker) => ticker.trim().toUpperCase())
    .filter(Boolean);
}

function dateLabel(value: string | null) {
  return value ? value.slice(0, 10) : "n/a";
}

function readable(value: string) {
  return value.replaceAll("_", " ");
}

function ToolError({ message }: { message: string }) {
  return (
    <div className="notice error tool-notice" role="alert">
      <CircleAlert size={18} aria-hidden="true" />
      <div>
        <strong>Research request failed</strong>
        <p>{message}</p>
      </div>
    </div>
  );
}

function FilingDeltaTool() {
  const [accession, setAccession] = useState("");
  const [asOf, setAsOf] = useState("");
  const [result, setResult] = useState<FilingDifference | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accession.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await fetchFilingDifference(accession.trim(), asOf || undefined));
    } catch (cause) {
      setResult(null);
      setError(cause instanceof Error ? cause.message : "The filing comparison failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="retrieve-lab" aria-labelledby="filing-delta-title">
      <header className="lab-heading">
        <span className="lab-icon"><FileDiff size={17} aria-hidden="true" /></span>
        <div>
          <p className="eyebrow">Disclosure change detection</p>
          <h3 id="filing-delta-title">Filing delta</h3>
          <p>Compare a filing with its point-in-time comparable and inspect passage-level changes.</p>
        </div>
      </header>

      <form className="lab-form delta-form" onSubmit={submit}>
        <label>
          <span>Accession number</span>
          <input
            aria-label="Filing accession number"
            value={accession}
            onChange={(event) => setAccession(event.target.value)}
            placeholder="0000320193-25-000079"
          />
        </label>
        <label>
          <span>Knowable as of</span>
          <input
            aria-label="Filing delta as-of date"
            type="date"
            value={asOf}
            onChange={(event) => setAsOf(event.target.value)}
          />
        </label>
        <button className="lab-primary" type="submit" disabled={loading || !accession.trim()}>
          {loading ? <LoaderCircle className="spin" size={16} /> : <ArrowRight size={16} />}
          {loading ? "Comparing" : "Compare"}
        </button>
      </form>

      {error && <ToolError message={error} />}
      {result && (
        <div className="delta-result">
          <div className="lab-statusbar">
            <span><strong>{result.company_ticker}</strong> {readable(result.comparison_basis)}</span>
            <span>{dateLabel(result.previous_available_at)} → {dateLabel(result.current_available_at)}</span>
            <span className="gate-pass"><ShieldCheck size={13} /> point-in-time gate passed</span>
          </div>
          <dl className="delta-stats">
            <div><dt>Added</dt><dd>{result.added_count}</dd></div>
            <div><dt>Removed</dt><dd>{result.removed_count}</dd></div>
            <div><dt>Rewritten</dt><dd>{result.materially_changed_count}</dd></div>
            <div><dt>Total delta</dt><dd>{result.changes.length}</dd></div>
          </dl>
          <div className="delta-list">
            {result.changes.length === 0 ? (
              <p className="lab-empty">No passage-level changes were detected.</p>
            ) : result.changes.map((change, index) => (
              <details
                className="delta-change"
                key={`${change.section}-${change.change_type}-${change.before_fingerprint ?? "none"}-${change.after_fingerprint ?? "none"}`}
                open={index === 0}
              >
                <summary>
                  <span className={`delta-kind ${change.change_type}`}>{readable(change.change_type)}</span>
                  <strong>{change.section}</strong>
                  <span>{change.similarity === null ? "" : `${Math.round(change.similarity * 100)}% similar`}</span>
                </summary>
                <div className="delta-copy">
                  {change.before_text && <div><span>Prior filing</span><p>{change.before_text}</p></div>}
                  {change.after_text && <div><span>Current filing</span><p>{change.after_text}</p></div>}
                </div>
              </details>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function formatFactValue(value: string, unit: string | null, metric: CanonicalMetric) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  if (metric === "eps") return numeric.toFixed(2);
  if (Math.abs(numeric) >= 1_000_000) {
    return new Intl.NumberFormat("en-US", {
      notation: "compact",
      maximumFractionDigits: 2,
    }).format(numeric);
  }
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(numeric)}${unit ? ` ${unit}` : ""}`;
}

function FactTapeTool() {
  const [tickers, setTickers] = useState("");
  const [metric, setMetric] = useState<CanonicalMetric | "all">("revenue");
  const [asOf, setAsOf] = useState("");
  const [policy, setPolicy] = useState<"latest" | "as_reported" | "all">("as_reported");
  const [result, setResult] = useState<FinancialFactsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tickers.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await fetchFinancialFacts({
        tickers: splitTickers(tickers),
        metrics: metric === "all" ? [] : [metric],
        asOf: asOf || undefined,
        restatementPolicy: policy,
        limit: 100,
      }));
    } catch (cause) {
      setResult(null);
      setError(cause instanceof Error ? cause.message : "The fact query failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="retrieve-lab" aria-labelledby="fact-tape-title">
      <header className="lab-heading">
        <span className="lab-icon"><Braces size={17} aria-hidden="true" /></span>
        <div>
          <p className="eyebrow">Structured XBRL</p>
          <h3 id="fact-tape-title">Point-in-time fact tape</h3>
          <p>Query canonical fundamentals with explicit restatement and availability policies.</p>
        </div>
      </header>

      <form className="lab-form fact-form" onSubmit={submit}>
        <label>
          <span>Tickers</span>
          <input
            aria-label="Fact tape tickers"
            value={tickers}
            onChange={(event) => setTickers(event.target.value)}
            placeholder="AAPL, MSFT"
          />
        </label>
        <label>
          <span>Metric</span>
          <select aria-label="Canonical metric" value={metric} onChange={(event) => setMetric(event.target.value as CanonicalMetric | "all")}>
            <option value="all">All canonical metrics</option>
            {METRICS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </label>
        <label>
          <span>Restatements</span>
          <select aria-label="Restatement policy" value={policy} onChange={(event) => setPolicy(event.target.value as typeof policy)}>
            <option value="as_reported">As originally reported</option>
            <option value="latest">Latest restatement</option>
            <option value="all">Show all versions</option>
          </select>
        </label>
        <label>
          <span>Knowable as of</span>
          <input aria-label="Fact tape as-of date" type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} />
        </label>
        <button className="lab-primary" type="submit" disabled={loading || !tickers.trim()}>
          {loading ? <LoaderCircle className="spin" size={16} /> : <ArrowRight size={16} />}
          {loading ? "Loading" : "Run query"}
        </button>
      </form>

      {error && <ToolError message={error} />}
      {result && (
        <div className="facts-result">
          <div className="lab-statusbar">
            <span><strong>{result.facts.length}</strong> reported facts</span>
            <span>{policy === "as_reported" ? "original-vintage values" : readable(policy)}</span>
            <span className="gate-pass"><CheckCircle2 size={13} /> source accession retained</span>
          </div>
          <div className="lab-table-wrap">
            <table className="lab-table facts-table">
              <thead><tr><th>Issuer</th><th>Metric</th><th className="num">Value</th><th>Period</th><th>Available</th><th>Source</th></tr></thead>
              <tbody>
                {result.facts.map((fact, index) => (
                  <tr key={`${fact.accession_number}-${fact.concept}-${fact.period_end}-${index}`}>
                    <td><strong>{fact.ticker}</strong><small>{fact.form_type ?? "filing"}</small></td>
                    <td>{readable(fact.canonical_metric)}<small>{fact.is_restatement ? "restated" : fact.concept}</small></td>
                    <td className="num"><strong>{formatFactValue(fact.value, fact.unit, fact.canonical_metric)}</strong></td>
                    <td>{fact.fiscal_year ?? "—"} {fact.fiscal_period ?? ""}<small>{dateLabel(fact.period_end)}</small></td>
                    <td>{dateLabel(fact.available_at)}</td>
                    <td><span className="mono-clip" title={fact.accession_number}>{fact.accession_number}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.facts.length === 0 && <p className="lab-empty">No reported facts matched this point-in-time query.</p>}
        </div>
      )}
    </section>
  );
}

function PanelExportTool() {
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
      setError(cause instanceof Error ? cause.message : "The panel build failed.");
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
      setError(cause instanceof Error ? cause.message : "The panel export failed.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <section className="retrieve-lab" aria-labelledby="panel-export-title">
      <header className="lab-heading">
        <span className="lab-icon"><Layers3 size={17} aria-hidden="true" /></span>
        <div>
          <p className="eyebrow">Leakage-safe research dataset</p>
          <h3 id="panel-export-title">Panel builder</h3>
          <p>Materialize issuer-period text and XBRL features with source-level provenance.</p>
        </div>
      </header>

      <form className="lab-form panel-form" onSubmit={build}>
        <label>
          <span>Tickers · blank = universe</span>
          <input aria-label="Panel tickers" value={tickers} onChange={(event) => setTickers(event.target.value)} placeholder="AAPL, MSFT" />
        </label>
        <label><span>Period from</span><input aria-label="Panel period from" type="date" value={from} onChange={(event) => setFrom(event.target.value)} /></label>
        <label><span>Period to</span><input aria-label="Panel period to" type="date" value={to} onChange={(event) => setTo(event.target.value)} /></label>
        <label><span>Knowable as of</span><input aria-label="Panel as-of date" type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} /></label>
        <div className="lab-control">
          <span>Forms</span>
          <div className="lab-chips">
            {FORM_OPTIONS.map((form) => <button key={form} type="button" className={forms.includes(form) ? "on" : undefined} onClick={() => toggleForm(form)}>{form}</button>)}
          </div>
        </div>
        <label><span>Row limit</span><input aria-label="Panel row limit" type="number" min={25} max={10000} step={25} value={limit} onChange={(event) => setLimit(Math.min(10000, Math.max(25, Number(event.target.value) || 25)))} /></label>
        <button className="lab-primary" type="submit" disabled={loading || forms.length === 0}>
          {loading ? <LoaderCircle className="spin" size={16} /> : <ArrowRight size={16} />}
          {loading ? "Building" : "Build preview"}
        </button>
      </form>

      {error && <ToolError message={error} />}
      {result && (
        <div className="panel-result">
          <div className="panel-manifest">
            <div><span>Rows</span><strong>{result.rows.length.toLocaleString()}</strong></div>
            <div><span>Feature version</span><strong>{result.feature_version}</strong></div>
            <div><span>Corpus snapshot</span><strong title={result.corpus_snapshot_id}>{result.corpus_snapshot_id.slice(0, 12)}</strong></div>
            <div className="manifest-gate"><ShieldCheck size={16} /><span>Point-in-time validation</span><strong>Passed</strong></div>
            <label className="export-format"><span>Format</span><select aria-label="Panel export format" value={format} onChange={(event) => setFormat(event.target.value as typeof format)}><option value="parquet">Parquet</option><option value="csv">CSV</option><option value="json">JSON</option></select></label>
            <button type="button" className="lab-download" onClick={download} disabled={downloading} title="Download research panel">
              {downloading ? <LoaderCircle className="spin" size={16} /> : <Download size={16} />}
              {downloading ? "Preparing" : "Export"}
            </button>
          </div>
          <div className="lab-table-wrap">
            <table className="lab-table panel-table">
              <thead><tr><th>Issuer</th><th>Period</th><th>Form</th><th className="num">Similarity</th><th className="num">Risk Δ</th><th className="num">Op. margin</th><th>Available</th></tr></thead>
              <tbody>
                {result.rows.slice(0, 8).map((row) => (
                  <tr key={row.accession_number}>
                    <td><strong>{row.ticker}</strong></td>
                    <td>{dateLabel(row.period_end)}</td>
                    <td>{row.form_type}</td>
                    <td className="num">{row.disclosure_similarity === null ? "—" : row.disclosure_similarity.toFixed(3)}</td>
                    <td className="num">{(row.risk_added_passages ?? 0) - (row.risk_removed_passages ?? 0)}</td>
                    <td className="num">{row.operating_margin === null ? "—" : `${(row.operating_margin * 100).toFixed(1)}%`}</td>
                    <td>{dateLabel(row.available_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.rows.length === 0 && <p className="lab-empty">No issuer-period rows matched these controls.</p>}
        </div>
      )}
    </section>
  );
}

export function RetrieveResearchTool({ tool }: { tool: ResearchTool }) {
  if (tool === "delta") return <FilingDeltaTool />;
  if (tool === "facts") return <FactTapeTool />;
  return <PanelExportTool />;
}
