import type { Metadata } from "next";
import Link from "next/link";
import { ArrowDown, ArrowUpRight } from "lucide-react";

import { LoopVideo } from "./loop-video";

export const metadata: Metadata = {
  title: "About — FDRE",
  description:
    "Why FDRE was built: layout-aware retrieval, citation verification, and calibrated abstention over SEC filings.",
};

export default function About() {
  return (
    <div className="site-shell">
      <section className="about-hero">
        <header className="hd-nav light">
          <Link className="hd-brand" href="/" aria-label="FDRE home">
            <span className="hd-mark">F</span>
            <span>
              <strong>FDRE</strong>
              <small>thefdre.com</small>
            </span>
          </Link>
          <nav className="hd-links" aria-label="Site">
            <Link href="/">Search</Link>
            <Link className="on" href="/about">
              About
            </Link>
          </nav>
          <div className="hd-right">
            <a
              className="hd-pill"
              href="https://github.com/kenchengkc/the-financial-document-retrieval-engine"
              target="_blank"
              rel="noreferrer"
            >
              View source
            </a>
          </div>
        </header>

        <div className="ih-stage">
          <div className="ih-panel left">
            <LoopVideo src="/about/panel-left.mp4" poster="/about/panel-left.png" />
            <div className="ih-motion" aria-hidden="true" />
            <div className="ih-tag">
              <span className="lv" aria-hidden="true" /> loops · 10s
            </div>
          </div>

          <div className="ih-card">
            <p className="hd-eyebrow">About FDRE</p>
            <h1>
              Built so every answer <span className="accent">shows its work</span>
            </h1>
            <p className="lede">
              Most financial search tools hand you a passage and hope. FDRE was built the other
              way around — retrieval, verification, and the willingness to say &ldquo;not enough
              evidence&rdquo; came first.
            </p>
            <div className="ih-meta">
              <span>Layout-aware retrieval</span>
              <span className="sep" aria-hidden="true" />
              <span>Citation verification</span>
              <span className="sep" aria-hidden="true" />
              <span>Calibrated abstention</span>
            </div>
            <a className="ih-down" href="#methodology" aria-label="Scroll to methodology">
              <ArrowDown size={18} strokeWidth={1.8} />
            </a>
          </div>

          <div className="ih-panel right">
            <LoopVideo src="/about/panel-right.mp4" poster="/about/panel-right.png" />
            <div className="ih-motion" aria-hidden="true" />
            <div className="ih-tag">
              <span className="lv" aria-hidden="true" /> loops · 10s
            </div>
          </div>
        </div>
      </section>

      <main>
        <section className="architecture" id="methodology">
          <div>
            <p className="eyebrow">Methodology</p>
            <h2>Index offline, retrieve live</h2>
            <p>
              FDRE batch-indexes filings into a <strong>pgvector</strong> store, then runs a
              bounded <strong>LangGraph retrieval agent</strong> on every question: hybrid
              embedding + keyword search, reranking, verified citations, and abstention when
              evidence is weak.
            </p>
          </div>
          <ol>
            <li>Batch ingest: parse filings, chunk text and tables</li>
            <li>Vector index: embed chunks into pgvector (Voyage)</li>
            <li>Live query: hybrid RAG + rerank via LangGraph agent</li>
            <li>Citation verification on every claim</li>
            <li>Answer or abstention — no hallucination fallback</li>
          </ol>
          <a
            href="https://github.com/kenchengkc/the-financial-document-retrieval-engine#architecture"
            target="_blank"
            rel="noreferrer"
          >
            Architecture <ArrowUpRight size={15} />
          </a>
        </section>
      </main>
    </div>
  );
}
