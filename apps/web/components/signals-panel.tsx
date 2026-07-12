"use client";

import {
  CheckCircle2,
  CircleAlert,
  CircleSlash,
  FlaskConical,
  HelpCircle,
  LoaderCircle,
  TrendingUp,
} from "lucide-react";
import { useEffect, useState } from "react";

import { fetchSignalStudies } from "@/lib/api";
import type {
  ComponentResult,
  SignalCorrelation,
  SignalStudyResponse,
  SignalWindow,
} from "@/lib/types";

const WINDOW_LABELS: Record<string, string> = {
  "0:1": "Filing day",
  "-1:1": "Around filing",
  "1:5": "+1 week",
  "1:21": "+1 month",
  "1:63": "+1 quarter",
};

const SIGNAL_LABELS: Record<string, string> = {
  disclosure_similarity: "Disclosure similarity",
  risk_expansion: "Risk expansion",
  filing_lateness: "Filing lateness",
  composite: "Composite",
};

function prettySignal(signal: string) {
  return SIGNAL_LABELS[signal] ?? signal;
}

function ComponentsPanel({
  windows,
  components,
  correlations,
  neutralization,
}: {
  windows: string[];
  components: ComponentResult[];
  correlations: SignalCorrelation[];
  neutralization?: string;
}) {
  const neutralLabel =
    neutralization === "period+sector" ? "Period + sector neutral" : "Period neutral";
  const signals = [...new Set(components.map((c) => c.signal))];
  const ordered = [
    ...signals.filter((s) => s !== "composite"),
    ...(signals.includes("composite") ? ["composite"] : []),
  ];
  const icFor = (signal: string, window: string) =>
    components.find((c) => c.signal === signal && c.window === window)
      ?.information_coefficient ?? null;
  return (
    <div className="comp-panel">
      <div className="comp-head">
        <div className="comp-head-row">
          <h3>Signal components — information coefficient by horizon</h3>
          <span className="comp-neutral">{neutralLabel}</span>
        </div>
        <p>
          Each component is weak; the composite (last row) averages their cross-sectionally
          standardized z-scores. The pairwise correlations near zero are why they are worth
          combining.
        </p>
      </div>
      <div className="comp-table">
        <div className="comp-row comp-th">
          <span>signal</span>
          {windows.map((w) => (
            <span key={w}>{windowLabel(w)}</span>
          ))}
        </div>
        {ordered.map((signal) => (
          <div
            className={`comp-row${signal === "composite" ? " comp-composite" : ""}`}
            key={signal}
          >
            <span className="comp-name">{prettySignal(signal)}</span>
            {windows.map((w) => {
              const ic = icFor(signal, w);
              return (
                <span
                  key={w}
                  className={`comp-ic ${ic === null ? "" : ic >= 0 ? "pos" : "neg"}`}
                >
                  {ic === null ? "—" : ic.toFixed(3)}
                </span>
              );
            })}
          </div>
        ))}
      </div>
      {correlations.length > 0 && (
        <div className="comp-corr">
          <span className="comp-corr-title">Pairwise correlation (near zero = diversifying)</span>
          <div className="comp-corr-list">
            {correlations.map((c) => (
              <span key={`${c.signal_a}-${c.signal_b}`} className="comp-corr-item">
                {prettySignal(c.signal_a)} · {prettySignal(c.signal_b)}
                <strong>{c.correlation === null ? "—" : c.correlation.toFixed(2)}</strong>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function windowLabel(window: string) {
  return WINDOW_LABELS[window] ?? window;
}

function pct(value: number | null, digits = 2) {
  return value === null ? "n/a" : `${(value * 100).toFixed(digits)}%`;
}

function outcomeName(study: SignalStudyResponse) {
  return study.report.outcome_name ?? "abnormal_return";
}

function significantCount(study: SignalStudyResponse) {
  const windows = study.report.results;
  const sig = windows.filter((w) => {
    const p = w.long_short_adjusted_p_value ?? w.long_short_p_value;
    return p !== null && p < 0.05;
  }).length;
  return { sig, total: windows.length };
}

function studyKey(study: SignalStudyResponse) {
  return `${study.report.signal_name}:${outcomeName(study)}`;
}

function isWindowSignificant(w: SignalWindow) {
  const p = w.long_short_adjusted_p_value ?? w.long_short_p_value;
  return p !== null && p < 0.05;
}

function bestAdjustedP(results: SignalWindow[]) {
  return Math.min(
    1,
    ...results.map((w) => w.long_short_adjusted_p_value ?? w.long_short_p_value ?? 1),
  );
}

function studyVerdict(study: SignalStudyResponse) {
  const results = study.report.results;
  const sig = results.filter(isWindowSignificant);
  if (sig.length === 0) {
    return {
      tone: "flat" as const,
      headline: "No tradeable edge",
      plain: `None of the ${results.length} holding horizons is statistically significant (best p = ${bestAdjustedP(results).toFixed(2)}). The pattern shows up directionally, but it is too weak and noisy to trade after costs.`,
    };
  }
  const horizons = sig.map((w) => windowLabel(w.window)).join(", ");
  return {
    tone: "sig" as const,
    headline: `Edge at ${sig.length} of ${results.length} horizons`,
    plain: `The long–short spread is statistically distinguishable from zero (p < 0.05) at ${horizons}.`,
  };
}

function StudyVerdict({ study }: { study: SignalStudyResponse }) {
  const v = studyVerdict(study);
  const Icon = v.tone === "sig" ? CheckCircle2 : CircleSlash;
  return (
    <div className={`sig-banner ${v.tone}`} role="status">
      <Icon size={22} aria-hidden="true" />
      <div>
        <p className="sig-banner-label">Verdict</p>
        <strong>{v.headline}</strong>
        <p className="sig-banner-plain">{v.plain}</p>
      </div>
    </div>
  );
}

function SummaryTable({
  results,
  isVolatility,
}: {
  results: SignalWindow[];
  isVolatility: boolean;
}) {
  return (
    <div className="sig-summary">
      <table>
        <thead>
          <tr>
            <th>Holding horizon</th>
            <th className="num">{isVolatility ? "High−low vol" : "Long–short return"}</th>
            <th className="num">Rank skill (IC)</th>
            <th>Verdict</th>
          </tr>
        </thead>
        <tbody>
          {results.map((w) => {
            const sig = isWindowSignificant(w);
            const rising = (w.long_short_mean ?? 0) >= 0;
            const p = w.long_short_adjusted_p_value ?? w.long_short_p_value;
            return (
              <tr key={w.window}>
                <td>
                  <strong>{windowLabel(w.window)}</strong>
                  <small>n = {w.sample_size.toLocaleString()}</small>
                </td>
                <td className={`num ${sig ? (rising ? "pos" : "neg") : ""}`}>
                  {pct(w.long_short_mean)}
                </td>
                <td className="num">
                  {w.information_coefficient === null ? "—" : w.information_coefficient.toFixed(3)}
                </td>
                <td>
                  <span className={`sig-verdict ${sig ? "sig" : "flat"}`}>
                    {sig ? `Significant ${rising ? "↑" : "↓"}` : "No edge"}
                  </span>
                  {p !== null && <small className="sig-p">p = {p.toFixed(2)}</small>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Glossary({ isVolatility }: { isVolatility: boolean }) {
  const outcome = isVolatility ? "next-period volatility" : "next-period return";
  const items: [string, string][] = [
    [
      "The 5 groups",
      `Every filing is sorted into 5 equal buckets by the signal (Group 1 = strongest, Group 5 = weakest). Each bar is that group's average ${outcome}.`,
    ],
    [
      "Long–short return",
      "What you would earn buying the top group and shorting the bottom — the tradeable edge if the signal works. Shown as Q5−Q1.",
    ],
    [
      "Rank skill (IC)",
      "How accurately the signal ranks winners vs. losers, from −1 to +1. 0 is a coin flip; genuinely useful signals run about 0.02–0.05.",
    ],
    [
      "Significant / p-value",
      "How likely the result is just luck. p < 0.05 (after adjusting for testing several horizons) means it is unlikely to be random.",
    ],
  ];
  return (
    <details className="sig-glossary">
      <summary>
        <HelpCircle size={14} aria-hidden="true" /> How to read this
      </summary>
      <dl>
        {items.map(([term, def]) => (
          <div key={term}>
            <dt>{term}</dt>
            <dd>{def}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function signalLabel(study: SignalStudyResponse) {
  if (study.report.signal_name === "composite") {
    const count = study.report.component_signals?.length ?? 0;
    return `Composite (${count} signals)`;
  }
  if (study.report.signal_name === "risk_factor_expansion") {
    return outcomeName(study) === "realized_volatility"
      ? "Risk expansion -> volatility"
      : "Risk expansion -> returns";
  }
  return outcomeName(study) === "realized_volatility"
    ? "Disclosure similarity -> volatility"
    : "Disclosure similarity -> returns";
}

function studyCopy(study: SignalStudyResponse) {
  if (study.report.signal_name === "composite") {
    return {
      headlinePrefix: "Can combining weak signals ",
      headlineAccent: "beat any single one",
      headlineSuffix: "?",
      lede:
        "Three point-in-time filing signals — disclosure similarity, net risk-factor expansion, and filing lateness — are each z-scored within their filing period and sector (cross-sectionally neutral, with a period fallback where a sector is thin), sign-aligned, and averaged into one composite. The Fundamental Law of Active Management (IR ≈ IC × √breadth) says uncorrelated signals combine into more information than any single one.",
      leftAxis: "← composite bearish",
      rightAxis: "composite bullish →",
      note:
        "The components are genuinely uncorrelated — the prerequisite for combination — but individually weak and sign-unstable across horizons, so naive equal-weighting does not beat the best single signal here. Sector-neutralizing the cross-section shrinks the raw ICs: part of a single signal's apparent edge was a sector tilt, not issuer-specific information. The realistic levers are breadth and IC-weighting the components out-of-sample, not a free lunch from averaging.",
    };
  }
  if (
    study.report.signal_name === "risk_factor_expansion" &&
    outcomeName(study) === "realized_volatility"
  ) {
    return {
      headlinePrefix: "Do expanded risk factors predict ",
      headlineAccent: "higher volatility",
      headlineSuffix: "?",
      lede:
        "Each filing is scored by net risk-factor expansion versus the prior comparable filing: added risk passages minus removed passages, knowable at acceptance. Quantiles are then tested against forward realized daily-return volatility.",
      leftAxis: "← fewer added risks",
      rightAxis: "more added risks →",
      note:
        "This is a reproducible risk-monitoring signal, not a trading claim. The outcome is raw realized volatility over each window; inference is bootstrap-based and remains sample-size sensitive.",
    };
  }
  return {
    headlinePrefix: "Do filings that ",
    headlineAccent: "change their language",
    headlineSuffix: " underperform?",
    lede:
      "A no-lookahead replication of the Lazy Prices anomaly (Cohen, Malloy & Nguyen, 2020). Each filing is scored by its disclosure similarity to the prior comparable filing, knowable only at acceptance, then sorted into quantiles.",
    leftAxis: "← revised filings underperform",
    rightAxis: "unchanged outperform →",
    note:
      "The signal is directionally consistent with Lazy Prices at short horizons but remains sample-size sensitive. Returns are market-adjusted gross of transaction costs and ignore borrow; the universe is survivorship-biased.",
  };
}

function QuantileChart({
  window,
  isVolatility,
}: {
  window: SignalWindow;
  isVolatility: boolean;
}) {
  const values = window.quantiles.map((q) => q.mean_abnormal_return ?? 0);
  const maxAbs = Math.max(0.0001, ...values.map((v) => Math.abs(v)));
  const n = window.quantiles.length;
  return (
    <div className="sig-quantiles">
      {window.quantiles.map((q) => {
        const value = q.mean_abnormal_return ?? 0;
        const positive = value >= 0;
        const edge = q.quantile === 1 || q.quantile === n ? " edge" : "";
        if (isVolatility) {
          // Volatility is a non-negative level, not a signed return: a 0-based
          // bar, not a diverging long/short chart.
          const width = (Math.abs(value) / maxAbs) * 100;
          return (
            <div className={`sig-qrow${edge}`} key={q.quantile}>
              <span className="sig-qlabel">Q{q.quantile}</span>
              <span className="sig-qtrack" aria-hidden="true">
                <span className="sig-qfill vol" style={{ left: "0%", width: `${width}%` }} />
              </span>
              <span className="sig-qval vol">{pct(value)}</span>
            </div>
          );
        }
        const width = (Math.abs(value) / maxAbs) * 50;
        return (
          <div className={`sig-qrow${edge}`} key={q.quantile}>
            <span className="sig-qlabel">Q{q.quantile}</span>
            <span className="sig-qtrack" aria-hidden="true">
              <span className="sig-qzero" />
              <span
                className={`sig-qfill ${positive ? "pos" : "neg"}`}
                style={{
                  width: `${width}%`,
                  left: positive ? "50%" : `${50 - width}%`,
                }}
              />
            </span>
            <span className={`sig-qval ${positive ? "pos" : "neg"}`}>{pct(value)}</span>
          </div>
        );
      })}
    </div>
  );
}

function WindowCard({
  window,
  leftAxis,
  rightAxis,
  isVolatility,
}: {
  window: SignalWindow;
  leftAxis: string;
  rightAxis: string;
  isVolatility: boolean;
}) {
  const adjustedP = window.long_short_adjusted_p_value ?? window.long_short_p_value;
  const significant = adjustedP !== null && adjustedP < 0.05;
  const rising = (window.long_short_mean ?? 0) >= 0;
  const verdict = significant ? `Significant ${rising ? "↑" : "↓"}` : "No edge";
  return (
    <article className="sig-card">
      <header>
        <div>
          <strong>{windowLabel(window.window)}</strong>
          <small>{window.sample_size.toLocaleString()} filings</small>
        </div>
        <span className={`sig-verdict ${significant ? "sig" : "flat"}`}>{verdict}</span>
      </header>
      <p className="sig-axis">
        <span>{leftAxis}</span>
        <span>{rightAxis}</span>
      </p>
      <QuantileChart window={window} isVolatility={isVolatility} />
      <footer className={significant ? "ok" : undefined}>
        <span>{isVolatility ? "High−low volatility" : "Long–short return"}</span>
        <strong>{pct(window.long_short_mean)}</strong>
      </footer>
    </article>
  );
}

export function SignalsPanel() {
  const [studies, setStudies] = useState<SignalStudyResponse[]>([]);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    void (async () => {
      const result = await fetchSignalStudies();
      if (active) {
        setStudies(result);
        setActiveKey(result[0] ? studyKey(result[0]) : null);
        setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  if (loading) {
    return (
      <div className="mode-panel">
        <div className="loading-state" role="status">
          <LoaderCircle className="spin" size={24} />
          <div>
            <h3>Loading the published signal studies</h3>
            <p>Reading the latest event-study experiments…</p>
          </div>
        </div>
      </div>
    );
  }

  if (!studies.length) {
    return (
      <div className="mode-panel">
        <div className="notice error" role="alert">
          <CircleAlert size={19} />
          <div>
            <strong>No signal study published yet</strong>
            <p>Run `retrieval_pipeline signal-study` to compute and publish one.</p>
          </div>
        </div>
      </div>
    );
  }

  const study = studies.find((candidate) => studyKey(candidate) === activeKey) ?? studies[0];
  const report = study.report;
  const copy = studyCopy(study);
  const confidence = report.config.confidence_level ?? 0.95;
  const isVol = outcomeName(study) === "realized_volatility";
  return (
    <div className="mode-panel">
      {studies.length > 1 && (
        <div className="sig-tabs" role="tablist" aria-label="Signal studies">
          {studies.map((candidate) => {
            const key = studyKey(candidate);
            const { sig, total } = significantCount(candidate);
            return (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={key === studyKey(study)}
                className={key === studyKey(study) ? "on" : undefined}
                onClick={() => setActiveKey(key)}
              >
                <span className="sig-tab-name">{signalLabel(candidate)}</span>
                <span className={`sig-tab-verdict${sig > 0 ? " has" : ""}`}>
                  {sig > 0 ? `${sig}/${total} horizons sig` : "no edge"}
                </span>
              </button>
            );
          })}
        </div>
      )}
      <div className="panel-intro">
        <p className="eyebrow">Point-in-time signal study</p>
        <h2>
          {copy.headlinePrefix}
          <span className="accent">{copy.headlineAccent}</span>
          {copy.headlineSuffix}
        </h2>
        <p className="panel-lede">{copy.lede}</p>
      </div>

      <StudyVerdict study={study} />

      <dl className="sig-stats">
        <div>
          <dt>Filing events</dt>
          <dd>{report.event_count.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Outcome</dt>
          <dd>{isVol ? "Volatility" : "Return"}</dd>
        </div>
        <div>
          <dt>Groups</dt>
          <dd>{report.n_quantiles}</dd>
        </div>
        <div>
          <dt>Bootstrap CI</dt>
          <dd>{Math.round(confidence * 100)}%</dd>
        </div>
      </dl>

      <SummaryTable results={report.results} isVolatility={isVol} />

      <Glossary isVolatility={isVol} />

      <div className="sig-grid">
        {report.results.map((window) => (
          <WindowCard
            key={window.window}
            window={window}
            leftAxis={copy.leftAxis}
            rightAxis={copy.rightAxis}
            isVolatility={isVol}
          />
        ))}
      </div>

      {report.components && report.components.length > 0 && (
        <ComponentsPanel
          windows={report.results.map((w) => w.window)}
          components={report.components}
          correlations={report.signal_correlations ?? []}
          neutralization={report.neutralization}
        />
      )}

      <div className="sig-note">
        <FlaskConical size={14} aria-hidden="true" />
        <p>
          <strong>Honest reading:</strong> {copy.note} The sample grows as the filing-history
          corpus deepens.
        </p>
      </div>

      <p className="sig-foot">
        <TrendingUp size={13} aria-hidden="true" />
        experiment {study.experiment_id} · code {study.code_sha.slice(0, 7)} · published{" "}
        {study.created_at.slice(0, 10)}
      </p>
    </div>
  );
}
