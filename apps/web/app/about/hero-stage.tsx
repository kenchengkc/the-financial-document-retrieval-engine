"use client";

import { ArrowDown } from "lucide-react";
import { useEffect, useRef } from "react";

// The two arched videos hold their first frame (the poster is the exact frame 0)
// until BOTH are ready, then start together so the load -> play transition is
// seamless and synchronized.
export function HeroStage() {
  const leftRef = useRef<HTMLVideoElement | null>(null);
  const rightRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const left = leftRef.current;
    const right = rightRef.current;
    if (!left || !right) return;
    left.muted = true;
    right.muted = true;
    let started = false;
    const startBoth = () => {
      if (started) return;
      if (left.readyState >= 3 && right.readyState >= 3) {
        started = true;
        left.currentTime = 0;
        right.currentTime = 0;
        void left.play().catch(() => {});
        void right.play().catch(() => {});
      }
    };
    left.addEventListener("canplay", startBoth);
    right.addEventListener("canplay", startBoth);
    startBoth();
    return () => {
      left.removeEventListener("canplay", startBoth);
      right.removeEventListener("canplay", startBoth);
    };
  }, []);

  return (
    <div className="ih-stage">
      <div className="ih-panel left">
        <video
          ref={leftRef}
          className="ih-video"
          src="/about/panel-left.mp4"
          poster="/about/panel-left.png"
          muted
          loop
          playsInline
          preload="auto"
        />
        <div className="ih-motion" aria-hidden="true" />
      </div>

      <div className="ih-card">
        <p className="hd-eyebrow">About FDRE</p>
        <h1>
          Research infrastructure that <span className="accent">shows its work</span>
        </h1>
        <p className="lede">
          FDRE converts SEC filings into auditable retrieval results, structured facts,
          point-in-time feature data, and reproducible event-study inputs for research teams.
        </p>
        <div className="ih-meta">
          <span>Research and data engineering</span>
          <span className="sep" aria-hidden="true" />
          <span>Quant research engineering</span>
          <span className="sep" aria-hidden="true" />
          <span>No trading-strategy claims</span>
        </div>
        <a className="ih-down" href="#see-it-work" aria-label="Scroll to the live demo">
          <ArrowDown size={18} strokeWidth={1.8} />
        </a>
      </div>

      <div className="ih-panel right">
        <video
          ref={rightRef}
          className="ih-video"
          src="/about/panel-right.mp4"
          poster="/about/panel-right.png"
          muted
          loop
          playsInline
          preload="auto"
        />
        <div className="ih-motion" aria-hidden="true" />
      </div>
    </div>
  );
}
