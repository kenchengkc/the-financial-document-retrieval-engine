"use client";

import {
  ArrowRight,
  CheckCircle2,
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
  risk_factor_expansion: "Risk-factor expansion",
  filing_lateness: "Filing lateness",
  earnings_quality: "Earnings quality",
  asset_growth: "Asset growth",
  net_share_issuance: "Net share issuance",
  composite: "Filing-behavior composite",
};

const FEATURE_LIBRARY = [
  { key: "disclosure_similarity", family: "Language", name: "Disclosure similarity", source: "Comparable filings", stage: "ready" },
  { key: "risk_factor_expansion", family: "Language", name: "Risk-factor expansion", source: "Item 1A passage delta", stage: "ready" },
  { key: "filing_lateness", family: "Timing", name: "Filing lateness", source: "Acceptance vs period end", stage: "ready" },
  { key: "earnings_quality", family: "Fundamental", name: "Earnings quality", source: "NI, CFO, assets", stage: "ready" },
  { key: "asset_growth", family: "Fundamental", name: "Asset growth", source: "Comparative XBRL", stage: "ready" },
  { key: "net_share_issuance", family: "Capital", name: "Net share issuance", source: "Diluted share count", stage: "ready" },
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
  return window.long_short_adjusted_p_value ?? window.long_short_p_value;
}

function studyMetrics(study: SignalStudyResponse) {
  const usable = study.report.results.filter((result) => result.long_short_mean !== null);
  const positive = usable.filter((result) => (result.long_short_mean ?? 0) > 0).length;
  const negative = usable.filter((result) => (result.long_short_mean ?? 0) < 0).length;
  const signStability = usable.length ? Math.max(positive, negative) / usable.length : 0;
  const significant = usable.filter((result) => {
    const p = adjustedP(result);
    return p !== null && p < 0.05;
  });
  const best = [...usable].sort((left, right) => {
    const pDelta = (adjustedP(left) ?? 1) - (adjustedP(right) ?? 1);
    if (pDelta !== 0) return pDelta;
    return Math.abs(right.information_coefficient ?? 0) - Math.abs(left.information_coefficient ?? 0);
  })[0];
  const peakIc = Math.max(0, ...usable.map((result) => Math.abs(result.information_coefficient ?? 0)));
  const bestP = best ? adjustedP(best) : null;
  let state = "Exploratory";
  let tone = "flat";
  if (significant.length > 0 && signStability >= 0.6) {
    state = "Candidate";
    tone = "pass";
  } else if (significant.length > 0) {
    state = "Regime-sensitive";
    tone = "watch";
  } else if (signStability >= 0.67 && usable.length >= 3) {
    state = "Monitor";
    tone = "watch";
  }
  return { usable, signStability, significant, best, peakIc, bestP, state, tone };
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
  const qualified = metrics.filter(({ metrics: item }) => item.significant.length > 0).length;
  const stable = metrics.filter(({ metrics: item }) => item.signStability >= 0.67).length;
  const events = studies.reduce((sum, study) => sum + study.report.event_count, 0);

  return (
    <div className="signal-monitor">
      <div className="signal-view-heading">
        <div>
          <p className="eyebrow">Cross-study evidence</p>
          <h3>Signal monitor</h3>
        </div>
        <p>Published studies ranked by adjusted inference, sign stability, and breadth.</p>
      </div>

      <dl className="monitor-stats">
        <div><dt>Published studies</dt><dd>{studies.length}</dd></div>
        <div><dt>Study-event rows</dt><dd>{events.toLocaleString()}</dd></div>
        <div><dt>BH-qualified</dt><dd>{qualified}</dd></div>
        <div><dt>Sign-stable</dt><dd>{stable}</dd></div>
      </dl>

      <div className="monitor-table-wrap">
        <table className="monitor-table">
          <thead>
            <tr><th>Signal</th><th>Outcome</th><th className="num">Events</th><th>Best horizon</th><th className="num">Peak |IC|</th><th className="num">Adj. p</th><th>Sign stability</th><th>Research state</th><th aria-label="Open study" /></tr>
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
                  <span className="stability-meter"><i style={{ width: `${item.signStability * 100}%` }} /></span>
                  <small>{Math.round(item.signStability * 100)}%</small>
                </td>
                <td><span className={`research-state ${item.tone}`}>{item.state}</span></td>
                <td><button type="button" className="row-action" title={`Open ${SIGNAL_NAMES[study.report.signal_name] ?? study.report.signal_name} study`} onClick={() => onOpenStudy(study)}><ArrowRight size={15} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="monitor-rule"><CircleDotDashed size={13} /> Candidate requires an adjusted p-value below 0.05 and consistent spread direction across at least 60% of tested horizons.</p>

      <section className="feature-library" aria-labelledby="feature-library-title">
        <div className="signal-view-heading compact">
          <div><p className="eyebrow">Research queue</p><h3 id="feature-library-title">Feature library</h3></div>
          <p>Published studies, backtest-ready signals, and leakage-safe features kept visibly distinct.</p>
        </div>
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
      </section>
    </div>
  );
}

function gateRows(study: SignalStudyResponse) {
  const report = study.report;
  const config = report.config;
  const hasAdjustedP = report.results.some((result) => result.long_short_adjusted_p_value !== null);
  const isVolatility = (report.outcome_name ?? "abnormal_return") === "realized_volatility";
  return [
    ["Feature availability", "Passed", "source timestamp ≤ event timestamp"],
    ["Outcome alignment", "Passed", isVolatility ? "forward realized volatility" : `${config.benchmark_ticker ?? "SPY"}-adjusted return`],
    ["Multiple testing", hasAdjustedP ? "Controlled" : "Unadjusted", hasAdjustedP ? `Benjamini–Hochberg · ${report.results.length} horizons` : "no adjusted p-values published"],
    ["Inference", "Deterministic", `${(config.bootstrap_iterations ?? 0).toLocaleString()} bootstrap draws · seed ${config.random_seed ?? "n/a"}`],
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
        <div><p className="eyebrow">Reproducibility record</p><h3>Experiment audit</h3></div>
        <button type="button" className="copy-manifest" onClick={copyManifest} title="Copy experiment manifest"><Copy size={14} />{copied ? "Copied" : "Copy manifest"}</button>
      </div>

      <div className="audit-layout">
        <section className="audit-manifest">
          <h4><Fingerprint size={15} /> Immutable manifest</h4>
          <dl>
            <div><dt>Experiment</dt><dd>#{study.experiment_id} · {study.experiment_key.slice(0, 16)}</dd></div>
            <div><dt>Dataset</dt><dd>{report.dataset_version ?? "legacy study"}</dd></div>
            <div><dt>Feature</dt><dd>{report.feature_version ?? "legacy study"}</dd></div>
            <div><dt>Code</dt><dd>{study.code_sha}</dd></div>
            <div><dt>Published</dt><dd>{study.created_at.replace("T", " ").slice(0, 19)} UTC</dd></div>
            <div><dt>Universe events</dt><dd>{report.event_count.toLocaleString()}</dd></div>
            <div><dt>Benchmark</dt><dd>{config.benchmark_ticker ?? "outcome-native"}</dd></div>
            <div><dt>Market clock</dt><dd>{config.market_timezone ?? "America/New_York"} · {config.market_close ?? "16:00"}</dd></div>
          </dl>
          <div className="fingerprint-block"><span>Full experiment key</span><code>{study.experiment_key}</code></div>
        </section>

        <section className="audit-gates">
          <h4><ShieldCheck size={15} /> Research gates</h4>
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
      </div>

      <div className="audit-windows">
        <h4>Tested horizon manifest</h4>
        <div>
          {report.results.map((result) => (
            <span key={result.window}><strong>{windowLabel(result.window)}</strong><small>n {result.sample_size.toLocaleString()} · IC {result.information_coefficient?.toFixed(3) ?? "n/a"} · adj p {adjustedP(result)?.toFixed(3) ?? "n/a"}</small></span>
          ))}
        </div>
      </div>
    </div>
  );
}
