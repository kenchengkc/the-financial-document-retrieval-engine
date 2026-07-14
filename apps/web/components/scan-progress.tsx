"use client";

import { Check, LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/**
 * Time-based progress for a request whose real progress we cannot observe
 * (the API returns a single response, not a stream). Instead of a smooth
 * mathematical curve — which reads as fake — the bar is a random walk:
 * irregular jumps, occasional bursts, and brief stalls, the way real work
 * ticks over. A soft ceiling that tracks elapsed time keeps the walk honest:
 * it climbs roughly linearly to ~98% at the expected duration, so there is no
 * dramatic end-of-bar braking and no long park just under the top. The parent
 * unmounts this on completion, which is the real 100%.
 *
 * The pipeline stages render as a checklist under the bar, driven by the same
 * fraction: done stages get a check, the current one a spinner.
 */
export function ScanProgress({
  estimateMs,
  stages,
}: {
  estimateMs: number;
  stages: string[];
}) {
  const [fraction, setFraction] = useState(0.02);
  const progressRef = useRef(0.02);

  useEffect(() => {
    const start = performance.now();
    let timer = 0;
    let cancelled = false;

    const tick = () => {
      if (cancelled) return;
      const ratio = (performance.now() - start) / Math.max(1, estimateMs);
      // Soft ceiling: roughly linear, ~98% at the expected duration, then a
      // slow drift so an overrun still shows visible motion instead of parking.
      const ceiling = Math.min(0.995, 0.08 + 0.9 * ratio);

      // Scale the walk so its expected pace covers ~95% across the estimate,
      // whether that is a 9s answer or a 30s deep scan.
      const pace = Math.min(3, Math.max(0.5, 22_000 / Math.max(1, estimateMs)));
      const roll = Math.random();
      let step: number;
      if (roll < 0.22) {
        step = 0; // stall — work pauses sometimes
      } else if (roll < 0.34) {
        step = (0.035 + Math.random() * 0.045) * pace; // burst — a batch lands at once
      } else {
        step = (0.004 + Math.random() * 0.022) * pace; // ordinary irregular tick
      }
      const next = Math.min(ceiling, progressRef.current + step);
      if (next > progressRef.current) {
        progressRef.current = next;
        setFraction(next);
      }
      timer = window.setTimeout(tick, 140 + Math.random() * 520);
    };

    timer = window.setTimeout(tick, 120);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
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
