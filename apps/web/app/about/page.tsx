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
    "SEC filing search, financial data, filing comparisons, and historical research data with cited sources.",
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
            <p className="eyebrow">Product tour</p>
            <h2 id="see-it-work-title">A walk-through of the research tools</h2>
            <p>
              See answers with citations, historical filing search, company comparisons, and filing
              event studies. Select a tool or let the tour continue.
            </p>
          </div>
          <SearchDemo />
          <p className="demo-foot">
            <Link href="/">Open the live console →</Link>
          </p>
        </section>

        <section className="proof-band" aria-labelledby="verified-scale">
          <div className="proof-heading">
            <p className="eyebrow">Live data coverage</p>
            <h2 id="verified-scale">Current coverage</h2>
            <p>
              These counts come from the production database. The S&amp;P 500 list uses current
              members, so it excludes companies that have left the index.
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
              <dd>Filing passages available for search</dd>
            </div>
            <div>
              <dt>512</dt>
              <dd>Vector dimensions</dd>
            </div>
          </dl>
        </section>

        <section className="specimen-band" aria-labelledby="specimen-title">
          <div className="proof-heading">
            <p className="eyebrow">Example outputs</p>
            <h2 id="specimen-title">What a result includes</h2>
            <p>
              A reported financial value linked to its filing, plus the search run that produced an
              answer and its citations.
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
                  Search run
                </span>
                <strong>Verified</strong>
              </div>
              <ol className="artifact-steps">
                <li>
                  <span>01</span>
                  <div>
                    <strong>Identify company</strong>
                    <small>META only</small>
                  </div>
                </li>
                <li>
                  <span>02</span>
                  <div>
                    <strong>Search text and data</strong>
                    <small>Text · tables · facts</small>
                  </div>
                </li>
                <li>
                  <span>03</span>
                  <div>
                    <strong>Check citation</strong>
                    <small>Exact source text match</small>
                  </div>
                </li>
              </ol>
              <div className="artifact-score">
                <span>Best match score</span>
                <strong>0.648</strong>
              </div>
            </div>
          </div>
        </section>

        <section className="proof-band" aria-labelledby="engineering-evidence">
          <div className="proof-heading">
            <p className="eyebrow">System design</p>
            <h2 id="engineering-evidence">Built for repeatable research</h2>
            <p>
              This is research software. It does not execute trades or provide portfolio
              recommendations.
            </p>
          </div>
          <div className="proof-grid">
            <article>
              <DatabaseZap size={20} aria-hidden="true" />
              <h3>Filing search</h3>
              <p>PostgreSQL full-text search and vector similarity search with pgvector.</p>
            </article>
            <article>
              <Clock3 size={20} aria-hidden="true" />
              <h3>Historical availability</h3>
              <p>SEC acceptance timestamps, filing availability dates, amendments, and as-of filtering.</p>
            </article>
            <article>
              <TableProperties size={20} aria-hidden="true" />
              <h3>Structured facts</h3>
              <p>SEC Company Facts plus standardized revenue, margins, cash flow, debt, and EPS.</p>
            </article>
            <article>
              <GitCompareArrows size={20} aria-hidden="true" />
              <h3>Filing differences</h3>
              <p>Comparable periods with added, removed, and materially changed passages.</p>
            </article>
            <article>
              <BarChart3 size={20} aria-hidden="true" />
              <h3>Research data exports</h3>
              <p>Versioned JSON, CSV, and Parquet company-period data with future-data checks.</p>
            </article>
            <article>
              <ScanSearch size={20} aria-hidden="true" />
              <h3>Operational records</h3>
              <p>Ingestion manifests, recovery metrics, data-quality checks, and experiment IDs.</p>
            </article>
          </div>
        </section>

        <section className="workflow-band" aria-labelledby="research-workflows">
          <div className="proof-heading">
            <p className="eyebrow">Research workflows</p>
            <h2 id="research-workflows">Six public examples</h2>
          </div>
          <ol>
            <li>
              <span>01</span>
              <div>
                <strong>Single-company risk search</strong>
                <p>Find filing passages by section and inspect matching scores and citations.</p>
              </div>
            </li>
            <li>
              <span>02</span>
              <div>
                <strong>Table and XBRL data</strong>
                <p>Search reported financial data with the linked filing and supporting text.</p>
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
                <strong>Topic search across companies</strong>
                <p>Search a topic across companies while showing evidence for each company.</p>
              </div>
            </li>
            <li>
              <span>05</span>
              <div>
                <strong>Research datasets and event studies</strong>
                <p>
                  Build historical company-period data and run benchmark-adjusted statistical tests.
                </p>
              </div>
            </li>
            <li>
              <span>06</span>
              <div>
                <strong>Published signal studies</strong>
                <p>
                  Four filing studies covering disclosures, risk, composite measures, and earnings
                  quality, with multiple-testing adjustments and clear results.
                </p>
              </div>
            </li>
          </ol>
        </section>

        <section className="architecture" id="methodology">
          <div>
            <p className="eyebrow">How it works</p>
            <h2>Prepare filings before search</h2>
            <p>
              FDRE preprocesses each question, searches filing text, tables, and financial data,
              ranks the results, checks citations, and returns an answer only when the sources
              support it.
            </p>
          </div>
          <ol>
            <li>SEC filing ingestion with acceptance timestamps</li>
            <li>Text and table parsing that preserves document structure</li>
            <li>Keyword and semantic search</li>
            <li>Financial data, filing comparisons, exports, and studies</li>
            <li>Answer with cited sources, or no answer</li>
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
