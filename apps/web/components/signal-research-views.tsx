"use client";

import {
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  CircleDotDashed,
  Copy,
  Fingerprint,
  ShieldCheck,
} from "lucide-react";
import { useState } from "react";

import type { SignalStudyResponse, SignalWindow } from "@/lib/types";

const WINDOW_LABELS: Record<string, string> = {
  "0:1": "Filing day",
  "-1:1": "Around filing",
  "1:5": "+1 week",
  "1:21": "+1 month",
  "1:63": "+1 quarter",
  "1:126": "+6 months",
  "1:252": "+12 months",
};

const SIGNAL_NAMES: Record<string, string> = {
  disclosure_similarity: "Disclosure similarity",
  risk_factor_churn: "Risk-factor churn",
  filing_delay_surprise: "Filing-delay surprise",
  risk_factor_expansion: "Risk-factor expansion",
  filing_lateness: "Filing lateness",
  earnings_quality: "Earnings quality",
  operating_profitability: "Operating profitability",
  operating_margin_momentum: "Margin momentum",
  asset_growth: "Asset growth",
  net_share_issuance: "Net share issuance",
  composite: "Filing-behavior composite",
};

const FEATURE_LIBRARY = [
  { key: "disclosure_similarity", family: "Language", name: "Disclosure similarity", source: "Comparable filings", stage: "ready" },
  { key: "risk_factor_churn", family: "Language", name: "Risk-factor churn", source: "Normalized Item 1A additions and removals", stage: "ready" },
  { key: "filing_delay_surprise", family: "Timing", name: "Filing-delay surprise", source: "Issuer-form expanding baseline", stage: "ready" },
  { key: "earnings_quality", family: "Fundamental", name: "Cash-conversion quality", source: "NI, CFO, average assets", stage: "ready" },
  { key: "operating_profitability", family: "Fundamental", name: "Operating profitability", source: "Operating income, average assets", stage: "ready" },
  { key: "operating_margin_momentum", family: "Fundamental", name: "Margin momentum", source: "Comparative annual XBRL", stage: "ready" },
  { key: "asset_growth", family: "Fundamental", name: "Asset growth", source: "Comparative XBRL", stage: "ready" },
  { key: "net_share_issuance", family: "Capital", name: "Net share issuance", source: "Shares outstanding with diluted fallback", stage: "ready" },
  { key: "section_novelty", family: "Language", name: "Section novelty", source: "Section fingerprints", stage: "feature" },
  { key: "topic_intensity", family: "Theme", name: "Topic intensity", source: "PIT topic counts", stage: "feature" },
  { key: "filing_complexity", family: "Structure", name: "Filing complexity", source: "Length, tables, numerics", stage: "feature" },
  { key: "margin_inflection", family: "Fundamental", name: "Margin inflection", source: "Canonical XBRL", stage: "feature" },
] as const;

function windowLabel(window: string) {
  return WINDOW_LABELS[window] ?? window;
}

function outcomeLabel(study: SignalStudyResponse) {
  return (study.report.outcome_name ?? "abnormal_return") === "realized_volatility"
    ? "Realized volatility"
    : "Abnormal return";
}

function adjustedP(window: SignalWindow) {
  return (
    window.suite_adjusted_p_value ??
    window.long_short_adjusted_p_value ??
    window.long_short_p_value
  );
}

function studyMetrics(study: SignalStudyResponse) {
  const usable = study.report.results.filter((result) => result.long_short_mean !== null);
  const positive = usable.filter((result) => (result.long_short_mean ?? 0) > 0).length;
  const signStability =
    study.report.quality?.direction_stability ?? (usable.length ? positive / usable.length : 0);
  const significant = usable.filter((result) => {
    const p = adjustedP(result);
    return p !== null && p < 0.05;
  });
  const selectedWindow = study.report.quality?.best_window;
  const best =
    usable.find((result) => result.window === selectedWindow) ??
    [...usable].sort((left, right) => {
      const pDelta = (adjustedP(left) ?? 1) - (adjustedP(right) ?? 1);
      if (pDelta !== 0) return pDelta;
      return (
        Math.abs(right.information_coefficient ?? 0) -
        Math.abs(left.information_coefficient ?? 0)
      );
    })[0];
  const peakIc =
    study.report.quality?.peak_absolute_ic ??
    Math.max(0, ...usable.map((result) => Math.abs(result.information_coefficient ?? 0)));
  const bestP = study.report.quality?.best_suite_adjusted_p_value ?? (best ? adjustedP(best) : null);
  const state = study.report.quality?.status ?? "Exploratory";
  const tone = state === "Validated" ? "pass" : state === "Promising" ? "watch" : "flat";
  const annualStability =
    study.report.quality?.stability_basis === "annual_periods" ? signStability : null;
  const periodsTested = study.report.quality?.periods_tested ?? 0;
  return {
    usable,
    signStability,
    annualStability,
    periodsTested,
    significant,
    best,
    peakIc,
    bestP,
    state,
    tone,
  };
}

export function SignalMonitor({
  studies,
  onOpenStudy,
}: {
  studies: SignalStudyResponse[];
  onOpenStudy: (study: SignalStudyResponse) => void;
}) {
  const metrics = studies
    .map((study) => ({ study, metrics: studyMetrics(study) }))
    .sort((left, right) => {
      const significance = right.metrics.significant.length - left.metrics.significant.length;
      if (significance !== 0) return significance;
      const adjustedEvidence = (left.metrics.bestP ?? 1) - (right.metrics.bestP ?? 1);
      if (adjustedEvidence !== 0) return adjustedEvidence;
      return right.metrics.signStability - left.metrics.signStability;
    });
  const adjustedPasses = metrics.filter(({ metrics: item }) => item.significant.length > 0).length;
  const stable = metrics.filter(
    ({ metrics: item }) => item.annualStability !== null && item.annualStability >= 0.67,
  ).length;
  const events = studies.reduce((sum, study) => sum + study.report.event_count, 0);

  return (
    <div className="signal-monitor">
      <div className="signal-view-heading">
        <div>
          <p className="eyebrow">Cross-study evidence</p>
          <h3>Signal comparison</h3>
        </div>
        <p>Compare published studies by adjusted evidence, annual stability, and sample breadth.</p>
      </div>

      <dl className="monitor-stats">
        <div><dt>Published studies</dt><dd>{studies.length}</dd></div>
        <div><dt>Study-event rows</dt><dd>{events.toLocaleString()}</dd></div>
        <div><dt>Pass adjusted test</dt><dd>{adjustedPasses}</dd></div>
        <div><dt>Year-stable</dt><dd>{stable}</dd></div>
      </dl>

      <div className="monitor-table-wrap">
        <table className="monitor-table">
          <thead>
            <tr><th>Signal</th><th>Outcome</th><th className="num">Events</th><th>Best horizon</th><th className="num">Peak |IC|</th><th className="num">Adjusted p</th><th>Annual stability</th><th>Research state</th><th aria-label="Open study" /></tr>
          </thead>
          <tbody>
            {metrics.map(({ study, metrics: item }) => (
              <tr key={`${study.report.signal_name}-${study.report.outcome_name ?? "abnormal_return"}`}>
                <td><strong>{SIGNAL_NAMES[study.report.signal_name] ?? study.report.signal_name}</strong><small>{study.report.feature_version ?? "versioned feature"}</small></td>
                <td>{outcomeLabel(study)}</td>
                <td className="num">{study.report.event_count.toLocaleString()}</td>
                <td>{item.best ? windowLabel(item.best.window) : "N/A"}</td>
                <td className="num">{item.peakIc ? item.peakIc.toFixed(3) : "N/A"}</td>
                <td className="num">{item.bestP === null ? "N/A" : item.bestP.toFixed(3)}</td>
                <td>
                  {item.annualStability === null ? (
                    <small>N/A</small>
                  ) : (
                    <>
                      <span className="stability-meter"><i style={{ width: `${item.annualStability * 100}%` }} /></span>
                      <small>{Math.round(item.annualStability * 100)}% · {item.periodsTested}y</small>
                    </>
                  )}
                </td>
                <td><span className={`research-state ${item.tone}`}>{item.state}</span></td>
                <td><button type="button" className="row-action" title={`Open ${SIGNAL_NAMES[study.report.signal_name] ?? study.report.signal_name} study`} onClick={() => onOpenStudy(study)}><ArrowRight size={15} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="monitor-rule"><CircleDotDashed size={13} /> Validated requires positive monotonic evidence in at least three annual cross-sections, aligned horizons, and an adjusted p-value below 0.05 across all published signal and horizon tests.</p>

      <details className="feature-library">
        <summary>
          <span><small>Research pipeline</small><strong>Feature library</strong></span>
          <span>{FEATURE_LIBRARY.length} features <ChevronDown size={15} aria-hidden="true" /></span>
        </summary>
        <p>Published studies, signals ready for historical testing, and features that exclude future data.</p>
        <div className="feature-library-grid">
          {FEATURE_LIBRARY.map((feature) => {
            const published = studies.some((study) => study.report.signal_name === feature.key);
            const status = published ? "Published" : feature.stage === "ready" ? "Backtest-ready" : "Feature live";
            return (
              <article key={feature.key}>
                <span>{feature.family}</span>
                <strong>{feature.name}</strong>
                <small>{feature.source}</small>
                <em className={published ? "published" : feature.stage}>{status}</em>
              </article>
            );
          })}
        </div>
      </details>
    </div>
  );
}

function gateRows(study: SignalStudyResponse) {
  const report = study.report;
  const config = report.config;
  const hasSuiteP = report.results.some((result) => result.suite_adjusted_p_value !== undefined);
  const isVolatility = (report.outcome_name ?? "abnormal_return") === "realized_volatility";
  return [
    ["Feature availability", "Passed", "source timestamp ≤ event timestamp"],
    ["Outcome alignment", report.quality?.outcome_aligned === false ? "Mismatch" : "Passed", isVolatility ? "forward realized volatility" : `${config.benchmark_ticker ?? "SPY"}-adjusted return`],
    ["Horizon alignment", report.quality?.horizon_aligned === false ? "Mismatch" : "Passed", report.quality?.preferred_windows.join(", ") || "signal-defined horizons"],
    ["Annual stability", (report.quality?.periods_tested ?? 0) >= 2 ? "Measured" : "Insufficient", `${report.quality?.periods_tested ?? 0} event-year cross-sections with at least ${report.quality?.period_sample_minimum ?? 50} filings`],
    ["Multiple testing", hasSuiteP ? "Controlled" : "Within-study only", hasSuiteP ? `Benjamini-Hochberg across ${report.quality?.suite_hypotheses ?? 0} published hypotheses` : `Benjamini-Hochberg across ${report.results.length} horizons`],
    ["Inference", "Deterministic", `${(config.bootstrap_iterations ?? 0).toLocaleString()} ${report.bootstrap_unit === "issuer" ? "issuer-cluster" : "filing-event"} bootstrap draws · seed ${config.random_seed ?? "n/a"}`],
    ["Neutralization", report.neutralization ? "Applied" : "Raw", report.neutralization ?? "unneutralized cross-section"],
    ["Walk-forward", config.walk_forward_splits?.length ? "Configured" : "Not configured", config.walk_forward_splits?.length ? `${config.walk_forward_splits.length} split dates` : "single pooled estimate"],
  ];
}

export function ExperimentAudit({ study }: { study: SignalStudyResponse }) {
  const [copied, setCopied] = useState(false);
  const report = study.report;
  const config = report.config;
  const manifest = {
    experiment_id: study.experiment_id,
    experiment_key: study.experiment_key,
    signal_name: report.signal_name,
    outcome_name: report.outcome_name ?? "abnormal_return",
    dataset_version: report.dataset_version,
    feature_version: report.feature_version,
    code_sha: study.code_sha,
    created_at: study.created_at,
    event_count: report.event_count,
    n_quantiles: report.n_quantiles,
    config,
  };

  async function copyManifest() {
    await navigator.clipboard.writeText(JSON.stringify(manifest, null, 2));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <div className="experiment-audit">
      <div className="signal-view-heading">
        <div><p className="eyebrow">Research design</p><h3>Method and reproducibility</h3></div>
        <p>Answer-quality checks and the exact setup behind this published result.</p>
      </div>

      <div className="audit-layout">
        <section className="audit-gates">
          <h4><ShieldCheck size={15} /> Research checks</h4>
          <ul>
            {gateRows(study).map(([label, status, detail]) => (
              <li key={label}>
                <CheckCircle2 size={16} aria-hidden="true" />
                <span><strong>{label}</strong><small>{detail}</small></span>
                <em>{status}</em>
              </li>
            ))}
          </ul>
        </section>

        <section className="audit-manifest">
          <h4><Fingerprint size={15} /> Study setup</h4>
          <dl>
            <div><dt>Run</dt><dd>#{study.experiment_id}</dd></div>
            <div><dt>Signal</dt><dd>{report.definition?.label ?? SIGNAL_NAMES[report.signal_name] ?? report.signal_name}</dd></div>
            <div><dt>Outcome</dt><dd>{outcomeLabel(study)}</dd></div>
            <div><dt>Sample</dt><dd>{report.event_count.toLocaleString()} filing events</dd></div>
            <div><dt>Feature</dt><dd>{report.feature_version ?? "legacy study"}</dd></div>
            <div><dt>Benchmark</dt><dd>{config.benchmark_ticker ?? "outcome-native"}</dd></div>
            <div><dt>Market clock</dt><dd>{config.market_timezone ?? "America/New_York"} · {config.market_close ?? "16:00"}</dd></div>
            <div><dt>Published</dt><dd>{study.created_at.replace("T", " ").slice(0, 19)} UTC</dd></div>
          </dl>
        </section>
      </div>

      <div className="audit-windows">
        <h4>Tested horizons</h4>
        <div>
          {report.results.map((result) => (
            <span key={result.window}><strong>{windowLabel(result.window)}</strong><small>n {result.sample_size.toLocaleString()} · {result.cluster_count?.toLocaleString() ?? "n/a"} issuers · IC {result.information_coefficient?.toFixed(3) ?? "n/a"} · adjusted p {adjustedP(result)?.toFixed(3) ?? "n/a"}</small></span>
          ))}
        </div>
      </div>

      <details className="audit-advanced">
        <summary>
          <Fingerprint size={15} aria-hidden="true" />
          <span><strong>Reproducibility details</strong><small>Run #{study.experiment_id} · {study.experiment_key.slice(0, 12)}</small></span>
          <ChevronDown size={15} aria-hidden="true" />
        </summary>
        <div className="audit-advanced-body">
          <p>The run fingerprint changes whenever the dataset, feature definition, code, or backtest settings change. It is used to reproduce and compare exact research runs.</p>
          <dl>
            <div><dt>Dataset version</dt><dd>{report.dataset_version ?? "legacy study"}</dd></div>
            <div><dt>Code version</dt><dd>{study.code_sha}</dd></div>
          </dl>
          <div className="fingerprint-block"><span>Full run fingerprint</span><code>{study.experiment_key}</code></div>
          <button type="button" className="copy-manifest" onClick={copyManifest} title="Copy reproducibility record"><Copy size={14} />{copied ? "Copied" : "Copy run record"}</button>
        </div>
      </details>
    </div>
  );
}
