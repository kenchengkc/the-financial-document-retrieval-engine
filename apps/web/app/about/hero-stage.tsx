"use client";

import { ArrowDown } from "lucide-react";
import Image from "next/image";
import { useEffect, useRef, useState } from "react";

// The two arched videos hold their first frame (the poster is the exact frame 0)
// until BOTH are ready, then start together so the load -> play transition is
// seamless and synchronized.
export function HeroStage() {
  const leftRef = useRef<HTMLVideoElement | null>(null);
  const rightRef = useRef<HTMLVideoElement | null>(null);
  const [videoLive, setVideoLive] = useState(false);

  useEffect(() => {
    const left = leftRef.current;
    const right = rightRef.current;
    if (!left || !right) return;
    const videos = [left, right];
    videos.forEach((video) => {
      video.defaultMuted = true;
      video.muted = true;
      video.pause();
    });

    let cancelled = false;
    let started = false;
    let revealFrame = 0;

    const ready = () => videos.every((video) => video.readyState >= 3);

    const startBoth = async () => {
      if (started) return;
      if (!ready()) return;
      started = true;
      setVideoLive(false);

      try {
        left.currentTime = 0;
        right.currentTime = 0;
        await Promise.all(videos.map((video) => video.play()));
        if (cancelled) return;
        revealFrame = window.requestAnimationFrame(() => {
          setVideoLive(true);
        });
      } catch {
        videos.forEach((video) => video.pause());
        setVideoLive(false);
      }
    };

    videos.forEach((video) => {
      video.addEventListener("loadeddata", startBoth);
      video.addEventListener("canplay", startBoth);
      video.addEventListener("canplaythrough", startBoth);
    });
    videos.forEach((video) => {
      video.load();
    });
    void startBoth();

    return () => {
      cancelled = true;
      if (revealFrame) {
        window.cancelAnimationFrame(revealFrame);
      }
      videos.forEach((video) => {
        video.removeEventListener("loadeddata", startBoth);
        video.removeEventListener("canplay", startBoth);
        video.removeEventListener("canplaythrough", startBoth);
      });
    };
  }, []);

  return (
    <div className="ih-stage">
      <div className={`ih-panel left ${videoLive ? "video-live" : ""}`}>
        <Image
          className="ih-poster"
          src="/about/panel-left.jpg"
          alt=""
          aria-hidden="true"
          fill
          priority
          sizes="(max-width: 700px) 0px, (max-width: 1100px) 170px, 248px"
        />
        <video
          ref={leftRef}
          className="ih-video"
          src="/about/panel-left.mp4"
          poster="/about/panel-left.jpg"
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

      <div className={`ih-panel right ${videoLive ? "video-live" : ""}`}>
        <Image
          className="ih-poster"
          src="/about/panel-right.jpg"
          alt=""
          aria-hidden="true"
          fill
          priority
          sizes="(max-width: 700px) 0px, (max-width: 1100px) 170px, 248px"
        />
        <video
          ref={rightRef}
          className="ih-video"
          src="/about/panel-right.mp4"
          poster="/about/panel-right.jpg"
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
