"use client";

import { ArrowRight, FileDiff, LoaderCircle, ShieldCheck } from "lucide-react";
import { FormEvent, useState } from "react";

import { fetchFilingDifference } from "@/lib/api";
import type { FilingDifference } from "@/lib/types";

import { dateLabel, readable, ToolError } from "./retrieve-research-shared";

function comparisonBasisLabel(value: string) {
  if (value === "prior_annual_period") return "vs. prior annual filing";
  if (value === "prior_period") return "vs. prior comparable filing";
  return readable(value);
}

export function FilingComparisonTool() {
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
    <section className="retrieve-lab" aria-labelledby="filing-comparison-title">
      <header className="lab-heading">
        <span className="lab-icon"><FileDiff size={17} aria-hidden="true" /></span>
        <div>
          <p className="eyebrow">Filing comparison</p>
          <h3 id="filing-comparison-title">Compare filing disclosures</h3>
          <p>
            Compare a filing with the prior comparable filing for that company. Review added,
            removed, and materially rewritten passages using only information available by the
            cutoff date.
          </p>
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
          <span>As-of date</span>
          <input
            aria-label="Comparison as-of date"
            type="date"
            value={asOf}
            onChange={(event) => setAsOf(event.target.value)}
          />
        </label>
        <button className="lab-primary" type="submit" disabled={loading || !accession.trim()}>
          {loading ? <LoaderCircle className="spin" size={16} /> : <ArrowRight size={16} />}
          {loading ? "Comparing" : "Compare filing"}
        </button>
      </form>

      {error && <ToolError message={error} />}
      {result && (
        <div className="delta-result">
          <div className="lab-statusbar">
            <span><strong>{result.company_ticker}</strong> {comparisonBasisLabel(result.comparison_basis)}</span>
            <span>{dateLabel(result.previous_available_at)} → {dateLabel(result.current_available_at)}</span>
            <span className="gate-pass"><ShieldCheck size={13} /> as-of date check passed</span>
          </div>
          <dl className="delta-stats">
            <div><dt>Added</dt><dd>{result.added_count}</dd></div>
            <div><dt>Removed</dt><dd>{result.removed_count}</dd></div>
            <div><dt>Rewritten</dt><dd>{result.materially_changed_count}</dd></div>
            <div><dt>Total changes</dt><dd>{result.changes.length}</dd></div>
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
