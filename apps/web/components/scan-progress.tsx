"use client";

import { useEffect, useRef, useState } from "react";

function formatClock(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/**
 * Time-based progress for a request whose real progress we cannot observe
 * (the API returns a single response, not a stream). The bar tracks elapsed time
 * against an expected duration: linear to 90%, then it eases toward — but never
 * reaches — 100%, so a slower-than-usual run keeps crawling instead of stalling
 * at a fake "done." The parent unmounts this on completion, which is the 100%.
 */
export function ScanProgress({ estimateMs }: { estimateMs: number }) {
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
  const fraction =
    ratio <= 0.9 ? ratio : 0.9 + 0.09 * (1 - Math.exp(-(ratio - 0.9) * 3));
  const pct = Math.min(99, Math.round(fraction * 100));
  const seconds = Math.floor(elapsed / 1000);
  const leftSec = Math.ceil((estimateMs - elapsed) / 1000);

  return (
    <div className="scan-progress">
      <div className="scan-progress-head">
        <span className="scan-progress-pct">{pct}%</span>
        <span className="scan-progress-time" aria-live="polite">
          {formatClock(seconds)} elapsed
          {leftSec > 0 ? ` · ~${leftSec}s left` : " · almost done…"}
        </span>
      </div>
      <div
        className="scan-progress-track"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Scan progress"
      >
        <div
          className="scan-progress-fill"
          style={{ width: `${Math.min(99, fraction * 100)}%` }}
        />
      </div>
    </div>
  );
}
