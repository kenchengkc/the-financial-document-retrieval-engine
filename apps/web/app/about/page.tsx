import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { Code2 } from "lucide-react";

import { HeroStage } from "./hero-stage";
import { SearchDemo } from "./search-demo";
import { SystemFlow } from "./system-flow";

export const metadata: Metadata = {
  title: "About | FDRE",
  description:
    "An animated tour of FDRE: SEC filing search, cited evidence, financial data, and point-in-time research workflows.",
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
            <h2 id="see-it-work-title">See the engine work</h2>
            <p>Four workflows. One animated tour.</p>
          </div>
          <SearchDemo />
          <p className="demo-foot">
            <Link href="/">Open the live console →</Link>
          </p>
        </section>

        <section className="proof-band" aria-labelledby="verified-scale">
          <div className="proof-heading">
            <p className="eyebrow">Live production coverage</p>
            <h2 id="verified-scale">Built on real filings</h2>
            <p>Live database counts. Current-index coverage is not backdated as historical membership.</p>
          </div>
          <dl className="proof-metrics">
            <div>
              <dt>
                {coverage
                  ? `${coverage.sp500_indexed_count} / ${coverage.sp500_catalog_count}`
                  : "499 / 499"}
              </dt>
              <dd>S&amp;P 500 primary tickers indexed</dd>
            </div>
            <div>
              <dt>{coverage ? coverage.document_count.toLocaleString() : "3,204"}</dt>
              <dd>SEC filings parsed and chunked</dd>
            </div>
            <div>
              <dt>{coverage ? coverage.chunk_count.toLocaleString() : "3,039,403"}</dt>
              <dd>Filing passages available for search</dd>
            </div>
            <div>
              <dt>512</dt>
              <dd>Vector dimensions</dd>
            </div>
          </dl>
        </section>

        <SystemFlow />
      </main>
    </div>
  );
}
