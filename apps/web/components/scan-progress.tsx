"use client";

import { Check, LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/**
 * Time-based progress for a request whose real progress we cannot observe
 * (the API returns a single response, not a stream). The percentage follows a
 * decelerating curve — quick early movement that keeps slowing, the way real
 * retrieval work feels — and asymptotically approaches (never reaches) 100%,
 * so a slower-than-usual run keeps crawling instead of stalling at a fake
 * "done." The parent unmounts this on completion, which is the real 100%.
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
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(0);

  useEffect(() => {
    startRef.current = performance.now();
    const id = window.setInterval(() => {
      setElapsed(performance.now() - startRef.current);
    }, 120);
    return () => window.clearInterval(id);
  }, []);

  const ratio = elapsed / Math.max(1, estimateMs);
  // 1 - e^(-2.2x): ~42% at a quarter of the estimate, ~67% at half, ~89% at
  // the estimate, then a slow crawl toward (never past) 99%.
  const fraction = Math.min(0.99, 1 - Math.exp(-2.2 * ratio));
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
