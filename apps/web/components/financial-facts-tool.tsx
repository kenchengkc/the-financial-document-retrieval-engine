"use client";

import { ArrowRight, Braces, CheckCircle2, LoaderCircle } from "lucide-react";
import { FormEvent, useState } from "react";

import { fetchFinancialFacts } from "@/lib/api";
import type { CanonicalMetric, FinancialFactsResponse } from "@/lib/types";

import { dateLabel, readable, splitTickers, ToolError } from "./retrieve-research-shared";

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

export function FinancialFactsTool() {
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
    <section className="retrieve-lab" aria-labelledby="financial-facts-title">
      <header className="lab-heading">
        <span className="lab-icon"><Braces size={17} aria-hidden="true" /></span>
        <div>
          <p className="eyebrow">XBRL financial data</p>
          <h3 id="financial-facts-title">Search reported financial data</h3>
          <p>
            Pull standardized filing values for selected companies and metrics as they were known at
            a chosen date. Select original values, latest restatements, or every reported version.
          </p>
        </div>
      </header>

      <form className="lab-form fact-form" onSubmit={submit}>
        <label>
          <span>Tickers</span>
          <input
            aria-label="Financial fact tickers"
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
          <span>Value version</span>
          <select aria-label="Restatement policy" value={policy} onChange={(event) => setPolicy(event.target.value as typeof policy)}>
            <option value="as_reported">Original filing value</option>
            <option value="latest">Latest available restatement</option>
            <option value="all">All reported versions</option>
          </select>
        </label>
        <label>
          <span>As-of date</span>
          <input aria-label="Financial fact as-of date" type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} />
        </label>
        <button className="lab-primary" type="submit" disabled={loading || !tickers.trim()}>
          {loading ? <LoaderCircle className="spin" size={16} /> : <ArrowRight size={16} />}
          {loading ? "Loading" : "Query facts"}
        </button>
      </form>

      {error && <ToolError message={error} />}
      {result && (
        <div className="facts-result">
          <div className="lab-statusbar">
            <span><strong>{result.facts.length}</strong> reported facts</span>
            <span>{policy === "as_reported" ? "originally reported values" : readable(policy)}</span>
            <span className="gate-pass"><CheckCircle2 size={13} /> source filing retained</span>
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
                    <td>{fact.fiscal_year ?? "N/A"} {fact.fiscal_period ?? ""}<small>{dateLabel(fact.period_end)}</small></td>
                    <td>{dateLabel(fact.available_at)}</td>
                    <td><span className="mono-clip" title={fact.accession_number}>{fact.accession_number}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.facts.length === 0 && <p className="lab-empty">No reported facts matched these companies, metrics, and date controls.</p>}
        </div>
      )}
    </section>
  );
}
