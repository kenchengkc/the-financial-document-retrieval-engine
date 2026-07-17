"use client";

import Image from "next/image";
import Link from "next/link";

const WAVE_PATH =
  "M0,58 C200,42 400,70 600,56 C800,42 1000,68 1200,54 L1200,120 L0,120 Z";
function Wave({ variant }: { variant: string }) {
  return (
    <svg className={`ld-wave ${variant}`} viewBox="0 0 1200 120" preserveAspectRatio="none">
      <path d={WAVE_PATH} />
    </svg>
  );
}

export function LandingHero({
  onExplore,
  apiOnline,
}: {
  onExplore: () => void;
  apiOnline: boolean | null;
}) {
  return (
    <section className="landing" id="top" data-screen-label="FDRE Home">
      <div className="ld-topline" />

      <div className="ld-scene" aria-hidden="true">
        <div className="ld-sky" />
        <div className="ld-glow" />
        <div className="ld-rays" />
        <div className="ld-cloud c1" />
        <div className="ld-cloud c2" />
        <div className="ld-cloud c3" />
        <div className="ld-sun" />
        <div className="ld-horizon" />
        <div className="ld-sea">
          <div className="ld-sun-sub" />
          <div className="ld-reflect" />
          <div className="ld-waves">
            <Wave variant="w1" />
            <Wave variant="w2" />
            <Wave variant="w3" />
            <Wave variant="w4" />
            <Wave variant="w5" />
          </div>
        </div>
        <div className="ld-mist" />
        <div className="ld-grain" />
        <div className="ld-scrim" />
      </div>

      <div className="ld-wrap">
        <nav className="ld-nav" aria-label="Primary">
          <Image
            className="ld-brand-img"
            src="/fdre-logo-white.png"
            alt="FDRE"
            width={629}
            height={230}
            priority
          />
          <div className="ld-links">
            <a className="on" href="#top">
              Home
            </a>
            <button type="button" onClick={onExplore}>
              Research
            </button>
            <Link href="/about">About</Link>
            <Link href="/contact">Contact</Link>
          </div>
        </nav>

        <section className="ld-hero">
          <p className="ld-eyebrow">For hedge funds &amp; research desks</p>
          <h1>
            Financial Document
            <br />
            Retrieval <em>Engine</em>
          </h1>
          <p className="ld-lede">
            Extracting market-moving insights from filings accurately, verifiably, and at
            scale. Every answer opens straight to its source.
          </p>
          <div className="ld-cta">
            <button type="button" className="ld-btn ld-btn-primary" onClick={onExplore}>
              Explore research
              <svg
                className="ld-arr"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </button>
          </div>
        </section>

        <div className="ld-meta">
          <div className="ld-pillars">
            <span className="ld-pillar">
              <span className="n">01</span>
              <span className="t">Layout-aware retrieval</span>
            </span>
            <span className="ld-dotsep" />
            <span className="ld-pillar">
              <span className="n">02</span>
              <span className="t">Citation verification</span>
            </span>
            <span className="ld-dotsep" />
            <span className="ld-pillar">
              <span className="n">03</span>
              <span className="t">Declines unsupported claims</span>
            </span>
          </div>
          <span className="ld-trust">
            <span className={`ld-live${apiOnline ? " on" : ""}`} />
            {apiOnline === false ? "SEC EDGAR index offline" : "Indexing SEC EDGAR in real time"}
          </span>
        </div>
      </div>
    </section>
  );
}
