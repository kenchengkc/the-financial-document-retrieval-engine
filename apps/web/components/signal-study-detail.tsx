import {
  ArrowDownRight,
  ArrowUpRight,
  Briefcase,
  CheckCircle2,
  CircleSlash,
  FlaskConical,
  HelpCircle,
  TrendingUp,
} from "lucide-react";

import type {
  ComponentResult,
  SignalConstituent,
  SignalCorrelation,
  SignalStudyResponse,
  SignalWindow,
} from "@/lib/types";

import { constituentCopy, outcomeName, studyCopy } from "./signal-study-copy";

const WINDOW_LABELS: Record<string, string> = {
  "0:1": "Filing day",
  "-1:1": "Around filing",
  "1:5": "+1 week",
  "1:21": "+1 month",
  "1:63": "+1 quarter",
  "1:126": "+6 months",
  "1:252": "+12 months",
};

const SIGNAL_LABELS: Record<string, string> = {
  disclosure_similarity: "Disclosure similarity",
  risk_factor_churn: "Risk churn",
  filing_delay_surprise: "Delay surprise",
  risk_factor_expansion: "Risk expansion",
  filing_lateness: "Filing lateness",
  earnings_quality: "Cash conversion",
  operating_profitability: "Profitability",
  operating_margin_momentum: "Margin momentum",
  asset_growth: "Asset growth",
  net_share_issuance: "Share issuance",
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
          <h3>Signal components: information coefficient by horizon</h3>
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
                  {ic === null ? "N/A" : ic.toFixed(3)}
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
                <strong>{c.correlation === null ? "N/A" : c.correlation.toFixed(2)}</strong>
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

function adjustedP(window: SignalWindow) {
  return (
    window.suite_adjusted_p_value ??
    window.long_short_adjusted_p_value ??
    window.long_short_p_value
  );
}

export function studyKey(study: SignalStudyResponse) {
  return `${study.report.signal_name}:${outcomeName(study)}`;
}

function isWindowSignificant(w: SignalWindow) {
  const p = adjustedP(w);
  return p !== null && p < 0.05;
}

function bestAdjustedP(results: SignalWindow[]) {
  return Math.min(
    1,
    ...results.map((w) => adjustedP(w) ?? 1),
  );
}

function studyVerdict(study: SignalStudyResponse) {
  const quality = study.report.quality;
  if (quality) {
    const stability =
      quality.stability_basis === "annual_periods"
        ? `annual direction stability = ${Math.round(quality.direction_stability * 100)}% across ${quality.periods_tested} years`
        : "annual stability is not yet measurable";
    return {
      tone:
        quality.status === "Validated"
          ? ("sig" as const)
          : quality.status === "Promising"
            ? ("watch" as const)
            : ("flat" as const),
      headline: `${quality.status} research signal`,
      plain: `${quality.reason} Best multiple-test-adjusted p = ${quality.best_suite_adjusted_p_value?.toFixed(3) ?? "n/a"}; ${stability}.`,
    };
  }
  const results = study.report.results;
  const sig = results.filter(isWindowSignificant);
  if (sig.length === 0) {
    return {
      tone: "flat" as const,
      headline: "No adjusted evidence",
      plain: `None of the ${results.length} holding horizons remains below p = 0.05 after correcting for the other published tests (best adjusted p = ${bestAdjustedP(results).toFixed(2)}). The signal is too weak and noisy to trade on its own after costs.`,
    };
  }
  const horizons = sig.map((w) => windowLabel(w.window)).join(", ");
  return {
    tone: "sig" as const,
    headline: `${sig.length} of ${results.length} horizons pass the adjusted test`,
    plain: `The spread remains below p = 0.05 after correcting across the published signal and horizon tests at ${horizons}. This older study has not yet received the full robustness rating.`,
  };
}

function StudyVerdict({ study }: { study: SignalStudyResponse }) {
  const v = studyVerdict(study);
  const Icon =
    v.tone === "sig" ? CheckCircle2 : v.tone === "watch" ? FlaskConical : CircleSlash;
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
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {results.map((w) => {
            const sig = isWindowSignificant(w);
            const rising = (w.long_short_mean ?? 0) >= 0;
            const p = adjustedP(w);
            return (
              <tr key={w.window}>
                <td>
                  <strong>{windowLabel(w.window)}</strong>
                  <small>
                    n = {w.sample_size.toLocaleString()}
                    {w.cluster_count ? ` · ${w.cluster_count.toLocaleString()} issuers` : ""}
                  </small>
                </td>
                <td className={`num ${sig ? (rising ? "pos" : "neg") : ""}`}>
                  {pct(w.long_short_mean)}
                </td>
                <td className="num">
                  {w.information_coefficient === null ? "N/A" : w.information_coefficient.toFixed(3)}
                </td>
                <td>
                  <span className={`sig-verdict ${sig ? "sig" : "flat"}`}>
                    {sig ? `Passes adjusted test ${rising ? "↑" : "↓"}` : "Does not pass"}
                  </span>
                  {p !== null && <small className="sig-p">adjusted p = {p.toFixed(2)}</small>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PeriodStability({
  study,
  isVolatility,
}: {
  study: SignalStudyResponse;
  isVolatility: boolean;
}) {
  const bestWindow = study.report.quality?.best_window;
  const minimumSample = study.report.quality?.period_sample_minimum ?? 50;
  const rows = (study.report.period_results ?? [])
    .filter(
      (row) =>
        bestWindow !== null && row.window === bestWindow && row.sample_size >= minimumSample,
    )
    .sort((left, right) => left.period.localeCompare(right.period));
  if (!bestWindow || rows.length < 2) {
    return null;
  }
  return (
    <section className="period-stability" aria-labelledby="annual-stability-title">
      <div className="period-stability-head">
        <div>
          <p className="eyebrow">Temporal robustness</p>
          <h3 id="annual-stability-title">Annual cross-sections</h3>
        </div>
        <p>
          {windowLabel(bestWindow)} held constant; each row uses at least {minimumSample} filing
          events from that year.
        </p>
      </div>
      <div className="sig-summary">
        <table>
          <thead>
            <tr>
              <th>Event year</th>
              <th className="num">Filings</th>
              <th className="num">Rank IC</th>
              <th className="num">{isVolatility ? "High-low vol" : "Long-short return"}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.period}-${row.window}`}>
                <td><strong>{row.period}</strong></td>
                <td className="num">{row.sample_size.toLocaleString()}</td>
                <td className={`num ${(row.information_coefficient ?? 0) >= 0 ? "pos" : "neg"}`}>
                  {row.information_coefficient?.toFixed(3) ?? "N/A"}
                </td>
                <td className={`num ${(row.long_short_mean ?? 0) >= 0 ? "pos" : "neg"}`}>
                  {pct(row.long_short_mean)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Glossary({ isVolatility }: { isVolatility: boolean }) {
  const outcome = isVolatility ? "next-period volatility" : "next-period return";
  const items: [string, string][] = [
    [
      "The 5 groups",
      `Every filing is sorted into 5 equal buckets by the signal (Group 1 = lowest score, Group 5 = highest score). Each bar is that group's average ${outcome}.`,
    ],
    [
      "Long–short return",
      "What you would earn buying the top group and shorting the bottom: the tradeable edge if the signal works. Shown as Q5−Q1.",
    ],
    [
      "Rank skill (IC)",
      "How accurately the signal ranks winners vs. losers, from −1 to +1. 0 is a coin flip; genuinely useful signals run about 0.02–0.05.",
    ],
    [
      "Adjusted p-value",
      "How likely the result is just luck after accounting for every published signal and horizon, not only the selected result. Values below 0.05 pass the adjusted test.",
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

export function signalTabLabel(study: SignalStudyResponse) {
  if (study.report.signal_name === "composite") {
    const count = study.report.component_signals?.length ?? 0;
    return `Composite (${count} signals)`;
  }
  return prettySignal(study.report.signal_name);
}

function Constituents({
  constituents,
  signalName,
}: {
  constituents: SignalConstituent[];
  signalName: string;
}) {
  const copy = constituentCopy(signalName);
  if (!constituents.length || !copy) {
    return null;
  }
  const longs = constituents.filter((c) => c.side === "long");
  const shorts = constituents.filter((c) => c.side === "short");
  const fmt = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
  const column = (
    rows: SignalConstituent[],
    tone: "long" | "short",
    Icon: typeof ArrowDownRight,
    title: string,
  ) => (
    <div className={`sig-const-col ${tone}`}>
      <p className="sig-const-title">
        <Icon size={15} aria-hidden="true" /> {title}
      </p>
      <ul>
        {rows.map((c) => (
          <li key={c.ticker}>
            <span className="sig-const-tk">{c.ticker}</span>
            <span className="sig-const-nm">{c.name}</span>
            <span className={`sig-const-v ${tone === "long" ? "good" : "warn"}`}>
              {fmt(c.value)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
  return (
    <div className="sig-constituents">
      <div className="sig-const-head">
        <h3>Where the S&amp;P 500 sits today</h3>
        <p>{copy.description}</p>
      </div>
      <div className="sig-const-cols">
        {column(longs, "long", ArrowDownRight, copy.longTitle)}
        {column(shorts, "short", ArrowUpRight, copy.shortTitle)}
      </div>
      <p className="sig-const-foot">
        {copy.footer} Illustrative factor research, not investment advice.
      </p>
    </div>
  );
}

function DeskApplications({ items }: { items: string[] }) {
  if (!items.length) {
    return null;
  }
  return (
    <div className="sig-desk">
      <div className="sig-desk-head">
        <h3>
          <Briefcase size={15} aria-hidden="true" /> How a desk would use this
        </h3>
        <p>
          A signal without standalone alpha is not a dead end. It changes how you screen,
          size, hedge, and combine. The realistic applications:
        </p>
      </div>
      <ul>
        {items.map((item) => {
          const [lead, ...rest] = item.split(": ");
          return (
            <li key={lead}>
              <strong>{lead}:</strong> {rest.join(": ")}
            </li>
          );
        })}
      </ul>
    </div>
  );
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
  const pValue = adjustedP(window);
  const significant = pValue !== null && pValue < 0.05;
  const rising = (window.long_short_mean ?? 0) >= 0;
  const verdict = significant ? `Passes adjusted test ${rising ? "↑" : "↓"}` : "Does not pass";
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

export function SignalStudyDetail({ study }: { study: SignalStudyResponse }) {
  const report = study.report;
  const copy = studyCopy(study);
  const isVol = outcomeName(study) === "realized_volatility";

  return (
    <>
      <div className="panel-intro">
        <p className="eyebrow">Historical filing event study</p>
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
          <dt>Research state</dt>
          <dd>{report.quality?.status ?? "Unrated"}</dd>
        </div>
        <div>
          <dt>Best adjusted p</dt>
          <dd>
            {(report.quality?.best_suite_adjusted_p_value ?? bestAdjustedP(report.results)).toFixed(3)}
          </dd>
        </div>
        <div>
          <dt>Annual stability</dt>
          <dd>
            {report.quality?.stability_basis === "annual_periods"
              ? `${Math.round(report.quality.direction_stability * 100)}% / ${report.quality.periods_tested}y`
              : "Not scored"}
          </dd>
        </div>
      </dl>

      <SummaryTable results={report.results} isVolatility={isVol} />
      <PeriodStability study={study} isVolatility={isVol} />
      <Glossary isVolatility={isVol} />

      {report.constituents && report.constituents.length > 0 && (
        <Constituents constituents={report.constituents} signalName={report.signal_name} />
      )}

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
          windows={report.results.map((window) => window.window)}
          components={report.components}
          correlations={report.signal_correlations ?? []}
          neutralization={report.neutralization}
        />
      )}

      <DeskApplications items={copy.desk} />

      <div className="sig-note">
        <FlaskConical size={14} aria-hidden="true" />
        <p>
          <strong>Interpretation:</strong> {copy.note} The sample grows as more filing history
          becomes available.
        </p>
      </div>

      <p className="sig-foot">
        <TrendingUp size={13} aria-hidden="true" />
        experiment {study.experiment_id} · code {study.code_sha.slice(0, 7)} · published{" "}
        {study.created_at.slice(0, 10)}
      </p>
    </>
  );
}
