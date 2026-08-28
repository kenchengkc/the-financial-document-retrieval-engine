"use client";

import { Check, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

const STORAGE_KEY = "fdre:ask-progress-estimate-ms";
const DEFAULT_ESTIMATE_MS = 2_000;
const MIN_ESTIMATE_MS = 900;
const MAX_ESTIMATE_MS = 15_000;

/**
 * Time-based progress for a request whose real progress cannot be observed until
 * the API returns. The bar follows elapsed wall-clock time against a learned
 * request-duration estimate rather than using random jumps. It reaches about
 * 95% at the expected duration, then drifts slowly toward 100% during overruns;
 * the parent unmounts it when the response actually arrives.
 *
 * The pipeline checklist is intentionally approximate because the answer API is
 * not streamed. Its purpose is to explain the work while the bar communicates
 * elapsed progress honestly.
 */
export function ScanProgress({
  estimateMs,
  stages,
}: {
  estimateMs: number;
  stages: string[];
}) {
  const [fraction, setFraction] = useState(0.04);

  useEffect(() => {
    const stored = Number(window.localStorage.getItem(STORAGE_KEY));
    const learnedEstimate =
      Number.isFinite(stored) && stored >= MIN_ESTIMATE_MS && stored <= MAX_ESTIMATE_MS
        ? stored
        : Math.min(DEFAULT_ESTIMATE_MS, estimateMs);
    const start = performance.now();
    let cancelled = false;

    const update = () => {
      if (cancelled) return;
      const elapsedMs = performance.now() - start;
      setFraction(progressForRatio(elapsedMs / Math.max(1, learnedEstimate)));
    };

    update();
    const timer = window.setInterval(update, 80);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      const observedMs = performance.now() - start;
      if (observedMs < 500) return;
      const nextEstimate = Math.min(
        MAX_ESTIMATE_MS,
        Math.max(MIN_ESTIMATE_MS, Math.round(learnedEstimate * 0.3 + observedMs * 0.7)),
      );
      window.localStorage.setItem(STORAGE_KEY, String(nextEstimate));
    };
  }, [estimateMs]);

  const pct = Math.round(fraction * 100);
  const activeStage = Math.min(stages.length - 1, Math.floor(fraction * stages.length));

  return (
    <div className="scan-progress">
      <div className="scan-progress-head">
        <span className="scan-progress-pct">{pct}%</span>
      </div>
      <div
        className="scan-progress-track"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Scan progress"
      >
        <div className="scan-progress-fill" style={{ width: `${fraction * 100}%` }} />
      </div>
      <ol className="scan-stages" aria-label="Pipeline stages">
        {stages.map((label, index) => {
          const state =
            index < activeStage ? "complete" : index === activeStage ? "active" : "pending";
          return (
            <li
              key={label}
              className={state}
              aria-current={state === "active" ? "step" : undefined}
            >
              <span className="scan-stage-icon" aria-hidden="true">
                {state === "complete" ? (
                  <Check size={13} strokeWidth={3} />
                ) : state === "active" ? (
                  <LoaderCircle className="spin" size={13} />
                ) : (
                  <span className="scan-stage-dot" />
                )}
              </span>
              {label}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function progressForRatio(ratio: number) {
  if (ratio <= 1) {
    return Math.max(0.04, 0.04 + Math.max(0, ratio) * 0.91);
  }
  const overrun = ratio - 1;
  return Math.min(0.995, 0.95 + 0.045 * (1 - Math.exp(-overrun * 1.4)));
}
