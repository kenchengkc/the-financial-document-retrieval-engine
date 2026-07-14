import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import {
  ArrowUpRight,
  BarChart3,
  CheckCircle2,
  Clock3,
  Code2,
  DatabaseZap,
  FileText,
  GitCompareArrows,
  ScanSearch,
  TableProperties,
} from "lucide-react";

import { HeroStage } from "./hero-stage";
import { SearchDemo } from "./search-demo";

export const metadata: Metadata = {
  title: "About | FDRE",
  description:
    "Measured engineering evidence for FDRE's point-in-time SEC research infrastructure.",
};

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

type Coverage = {
  sp500_indexed_count: number;
  sp500_catalog_count: number;
  document_count: number;
  chunk_count: number;
};

async function getCoverage(): Promise<Coverage | null> {
  try {
    // Build-time ISR fetch: cap it so a slow/unreachable API degrades to the
    // fallback (null) instead of hanging static generation until Vercel's 60s
    // worker timeout kills the whole build.
    const response = await fetch(`${API_URL}/coverage`, {
      next: { revalidate: 1800 },
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) return null;
    return (await response.json()) as Coverage;
  } catch {
    return null;
  }
}

export default async function About() {
  const coverage = await getCoverage();
  return (
    <div className="site-shell">
      <section className="about-hero">
        <header className="hd-nav light">
          <Link className="hd-brand" href="/" aria-label="FDRE home">
            <Image
              className="hd-brand-img"
              src="/fdre-logo-color.png"
              alt="FDRE"
              width={629}
              height={230}
              priority
            />
          </Link>
          <nav className="hd-links" aria-label="Site">
            <Link href="/">Console</Link>
            <Link className="on" href="/about">
              About
            </Link>
            <Link href="/contact">Contact</Link>
          </nav>
          <div className="hd-right">
            <a
              className="hd-pill"
              href="https://github.com/kenchengkc/the-financial-document-retrieval-engine"
              target="_blank"
              rel="noreferrer"
            >
              <Code2 size={16} aria-hidden="true" />
              <span className="hd-pill-label">View source</span>
            </a>
          </div>
        </header>

        <HeroStage />
      </section>

      <main>
        <section className="demo-band" id="see-it-work" aria-labelledby="see-it-work-title">
          <div className="proof-heading">
            <p className="eyebrow">See it work</p>
            <h2 id="see-it-work-title">A question in, audited evidence out</h2>
            <p>
              Every answer carries its citations, retrieval scores, and the discipline to abstain
              when the filings do not support a claim. This is the live console, replayed — pick a
              scenario or let it loop.
            </p>
          </div>
          <SearchDemo />
          <p className="demo-foot">
            <Link href="/">Open the live console →</Link>
          </p>
        </section>

        <section className="proof-band" aria-labelledby="verified-scale">
          <div className="proof-heading">
            <p className="eyebrow">Verified production corpus</p>
            <h2 id="verified-scale">Measured scale, not projected scale</h2>
            <p>
              These counts are read live from the production database. The S&amp;P 500 universe
              uses current constituents and is therefore survivorship-biased.
            </p>
          </div>
          <dl className="proof-metrics">
            <div>
              <dt>
                {coverage
                  ? `${coverage.sp500_indexed_count} / ${coverage.sp500_catalog_count}`
                  : "498 / 499"}
              </dt>
              <dd>S&amp;P 500 primary tickers indexed</dd>
            </div>
            <div>
              <dt>{coverage ? coverage.document_count.toLocaleString() : "2,762"}</dt>
              <dd>SEC filings parsed and chunked</dd>
            </div>
            <div>
              <dt>{coverage ? coverage.chunk_count.toLocaleString() : "2,712,277"}</dt>
              <dd>Chunks with stored embeddings</dd>
            </div>
            <div>
              <dt>512</dt>
              <dd>Voyage embedding dimensions</dd>
            </div>
          </dl>
        </section>

        <section className="specimen-band" aria-labelledby="specimen-title">
          <div className="proof-heading">
            <p className="eyebrow">Specimen outputs</p>
            <h2 id="specimen-title">What a single result looks like</h2>
            <p>
              A typed financial fact resolved to its filing, and the bounded retrieval run that
              produced a verified answer — the artifacts behind every console response.
            </p>
          </div>
          <div className="specimen-grid">
            <div className="ih-panel artifact-panel filing-artifact">
              <div className="artifact-heading">
                <span>
                  <FileText size={15} aria-hidden="true" />
                  SEC 10-Q
                </span>
                <strong>META</strong>
              </div>
              <div className="artifact-primary">
                <small>Net income</small>
                <strong>$26.77B</strong>
                <span>Three months ended March 31, 2026</span>
              </div>
              <dl className="artifact-facts">
                <div>
                  <dt>Revenue</dt>
                  <dd>$56.31B</dd>
                </div>
                <div>
                  <dt>Diluted EPS</dt>
                  <dd>$10.44</dd>
                </div>
              </dl>
              <p className="artifact-foot">Accepted April 30, 2026</p>
            </div>

            <div className="ih-panel artifact-panel retrieval-artifact">
              <div className="artifact-heading">
                <span>
                  <CheckCircle2 size={15} aria-hidden="true" />
                  Retrieval run
                </span>
                <strong>Verified</strong>
              </div>
              <ol className="artifact-steps">
                <li>
                  <span>01</span>
                  <div>
                    <strong>Resolve issuer</strong>
                    <small>META only</small>
                  </div>
                </li>
                <li>
                  <span>02</span>
                  <div>
                    <strong>Hybrid retrieve</strong>
                    <small>Text · tables · facts</small>
                  </div>
                </li>
                <li>
                  <span>03</span>
                  <div>
                    <strong>Verify citation</strong>
                    <small>100% text overlap</small>
                  </div>
                </li>
              </ol>
              <div className="artifact-score">
                <span>Top rerank score</span>
                <strong>0.648</strong>
              </div>
            </div>
          </div>
        </section>

        <section className="proof-band" aria-labelledby="engineering-evidence">
          <div className="proof-heading">
            <p className="eyebrow">Engineering evidence</p>
            <h2 id="engineering-evidence">Built for reproducible research</h2>
            <p>
              The public service is research infrastructure, not a low-latency trading system or
              a portfolio backtest.
            </p>
          </div>
          <div className="proof-grid">
            <article>
              <DatabaseZap size={20} aria-hidden="true" />
              <h3>Indexed retrieval</h3>
              <p>PostgreSQL GIN full-text search and float16 HNSW cosine search over pgvector.</p>
            </article>
            <article>
              <Clock3 size={20} aria-hidden="true" />
              <h3>Point-in-time controls</h3>
              <p>SEC acceptance timestamps, availability boundaries, amendments, and as-of filtering.</p>
            </article>
            <article>
              <TableProperties size={20} aria-hidden="true" />
              <h3>Structured facts</h3>
              <p>Raw Company Facts plus canonical revenue, margins, cash flow, debt, and EPS.</p>
            </article>
            <article>
              <GitCompareArrows size={20} aria-hidden="true" />
              <h3>Filing differences</h3>
              <p>Comparable periods with added, removed, and materially changed passages.</p>
            </article>
            <article>
              <BarChart3 size={20} aria-hidden="true" />
              <h3>Research panel</h3>
              <p>Versioned JSON, CSV, and Parquet issuer-period features with leakage checks.</p>
            </article>
            <article>
              <ScanSearch size={20} aria-hidden="true" />
              <h3>Auditable operations</h3>
              <p>Ingestion manifests, recovery metrics, data-quality audits, and experiment IDs.</p>
            </article>
          </div>
        </section>

        <section className="workflow-band" aria-labelledby="research-workflows">
          <div className="proof-heading">
            <p className="eyebrow">Research workflows</p>
            <h2 id="research-workflows">Six public demonstrations</h2>
          </div>
          <ol>
            <li>
              <span>01</span>
              <div>
                <strong>Single-name risk retrieval</strong>
                <p>Find section-aware evidence and inspect every retrieval score and citation.</p>
              </div>
            </li>
            <li>
              <span>02</span>
              <div>
                <strong>Table and XBRL extraction</strong>
                <p>Query typed financial facts with the linked filing and narrative evidence.</p>
              </div>
            </li>
            <li>
              <span>03</span>
              <div>
                <strong>Filing change detection</strong>
                <p>Compare the latest filing with its deterministic comparable period.</p>
              </div>
            </li>
            <li>
              <span>04</span>
              <div>
                <strong>Cross-sectional thematic research</strong>
                <p>Scan broad themes while capping evidence per issuer for diversified results.</p>
              </div>
            </li>
            <li>
              <span>05</span>
              <div>
                <strong>Panel export and event study</strong>
                <p>Export point-in-time features and run benchmark-adjusted statistical tests.</p>
              </div>
            </li>
            <li>
              <span>06</span>
              <div>
                <strong>Published signal studies</strong>
                <p>
                  Four point-in-time filing studies — disclosure, risk, composite, and earnings
                  quality — with multiple-testing-adjusted inference and honest verdicts.
                </p>
              </div>
            </li>
          </ol>
        </section>

        <section className="architecture" id="methodology">
          <div>
            <p className="eyebrow">Methodology</p>
            <h2>Index offline, retrieve live</h2>
            <p>
              The bounded <strong>LangGraph retrieval workflow</strong> preprocesses the query,
              routes text, tables, and structured facts, reranks evidence, applies an evidence
              gate, and verifies every citation before returning an answer.
            </p>
          </div>
          <ol>
            <li>Cached SEC ingest with acceptance timestamps</li>
            <li>Layout-aware text and table parsing</li>
            <li>Hybrid sparse and dense retrieval</li>
            <li>Typed facts, diffs, panels, and experiments</li>
            <li>Verified answer or deliberate abstention</li>
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
