"use client";

import { CircleAlert, FlaskConical, LoaderCircle, TrendingUp } from "lucide-react";
import { useEffect, useState } from "react";

import { fetchSignalStudy } from "@/lib/api";
import type { SignalStudyResponse, SignalWindow } from "@/lib/types";

const WINDOW_LABELS: Record<string, string> = {
  "0:1": "Filing day",
  "-1:1": "Around filing",
  "1:5": "+1 week",
  "1:21": "+1 month",
  "1:63": "+1 quarter",
};

function windowLabel(window: string) {
  return WINDOW_LABELS[window] ?? window;
}

function pct(value: number | null, digits = 2) {
  return value === null ? "n/a" : `${(value * 100).toFixed(digits)}%`;
}

function QuantileChart({ window }: { window: SignalWindow }) {
  const values = window.quantiles.map((q) => q.mean_abnormal_return ?? 0);
  const maxAbs = Math.max(0.0001, ...values.map((v) => Math.abs(v)));
  return (
    <div className="sig-quantiles">
      {window.quantiles.map((q) => {
        const value = q.mean_abnormal_return ?? 0;
        const width = (Math.abs(value) / maxAbs) * 50;
        const positive = value >= 0;
        return (
          <div className="sig-qrow" key={q.quantile}>
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

function WindowCard({ window }: { window: SignalWindow }) {
  const ic = window.information_coefficient;
  const significant = window.long_short_p_value !== null && window.long_short_p_value < 0.05;
  return (
    <article className="sig-card">
      <header>
        <div>
          <strong>{windowLabel(window.window)}</strong>
          <small>holding [{window.window}] · n = {window.sample_size}</small>
        </div>
        <div className="sig-ic">
          <span>IC</span>
          <strong>{ic === null ? "n/a" : ic.toFixed(3)}</strong>
          {window.ic_t_stat !== null && <em>t = {window.ic_t_stat.toFixed(2)}</em>}
        </div>
      </header>
      <p className="sig-axis">
        <span>← revised filings underperform</span>
        <span>unchanged outperform →</span>
      </p>
      <QuantileChart window={window} />
      <footer className={significant ? "ok" : undefined}>
        <span>
          Q5−Q1 long-short <strong>{pct(window.long_short_mean)}</strong>
        </span>
        <span>
          {window.long_short_p_value === null
            ? ""
            : significant
              ? `significant (p = ${window.long_short_p_value.toFixed(2)})`
              : `not significant (p = ${window.long_short_p_value.toFixed(2)})`}
        </span>
      </footer>
    </article>
  );
}

export function SignalsPanel() {
  const [study, setStudy] = useState<SignalStudyResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    void (async () => {
      const result = await fetchSignalStudy();
      if (active) {
        setStudy(result);
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
            <h3>Loading the published signal study</h3>
            <p>Reading the latest event-study experiment…</p>
          </div>
        </div>
      </div>
    );
  }

  if (!study) {
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

  const report = study.report;
  const confidence = report.config.confidence_level ?? 0.95;
  return (
    <div className="mode-panel">
      <div className="panel-intro">
        <p className="eyebrow">Point-in-time signal study</p>
        <h2>
          Do filings that <span className="accent">change their language</span> underperform?
        </h2>
        <p className="panel-lede">
          A no-lookahead replication of the “Lazy Prices” anomaly (Cohen, Malloy &amp; Nguyen,
          2020). Each filing is scored by its disclosure similarity to the prior comparable
          filing — knowable only at acceptance — then sorted into quintiles. Q1 is the most
          revised, Q5 the most unchanged; the chart shows forward market-adjusted returns.
        </p>
      </div>

      <dl className="sig-stats">
        <div>
          <dt>Filing events</dt>
          <dd>{report.event_count.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Benchmark</dt>
          <dd>{report.config.benchmark_ticker ?? "SPY"}</dd>
        </div>
        <div>
          <dt>Quantiles</dt>
          <dd>{report.n_quantiles}</dd>
        </div>
        <div>
          <dt>Bootstrap CI</dt>
          <dd>{Math.round(confidence * 100)}%</dd>
        </div>
      </dl>

      <div className="sig-grid">
        {report.results.map((window) => (
          <WindowCard key={window.window} window={window} />
        ))}
      </div>

      <div className="sig-note">
        <FlaskConical size={14} aria-hidden="true" />
        <p>
          <strong>Honest reading:</strong> the signal is directionally consistent with Lazy
          Prices (positive information coefficient at short horizons) but is not statistically
          significant at this sample size, and decays over the quarter. Returns are
          market-adjusted gross of transaction costs and ignore borrow; the universe is
          survivorship-biased. The value here is the reproducible, leakage-checked methodology —
          point-in-time features, bootstrap inference, and walk-forward — not a tradeable edge.
          The sample grows as the filing-history corpus deepens.
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
