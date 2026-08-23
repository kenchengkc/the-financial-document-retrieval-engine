import { ArrowDown, CheckCircle2, Database, FileCheck2 } from "lucide-react";

export function HeroStage() {
  return (
    <div className="ih-stage">
      <aside className="ih-panel ih-proof-panel ih-corpus-panel" aria-label="Data coverage">
        <span className="ih-proof-icon" aria-hidden="true">
          <Database size={18} />
        </span>
        <p>Data coverage</p>
        <strong>499 / 500</strong>
        <span className="ih-proof-label">S&amp;P 500 primary tickers available for search</span>
        <ul>
          <li>SEC 10-K and 10-Q filings</li>
          <li>Current members only; former members are excluded</li>
          <li>Live coverage and data-quality checks below</li>
        </ul>
      </aside>

      <div className="ih-card">
        <p className="hd-eyebrow">About FDRE</p>
        <h1>
          SEC filing research with <span className="accent">sources you can inspect</span>
        </h1>
        <p className="lede">
          FDRE turns SEC filings into cited search results, reported financial data, historical
          research data, and inputs for filing event studies.
        </p>
        <div className="ih-meta">
          <span>Research and data engineering</span>
          <span className="sep" aria-hidden="true" />
          <span>Quantitative research</span>
          <span className="sep" aria-hidden="true" />
          <span>No trading-strategy claims</span>
        </div>
        <a className="ih-down" href="#see-it-work" aria-label="Scroll to the live demo">
          <ArrowDown size={18} strokeWidth={1.8} />
        </a>
      </div>

      <aside className="ih-panel ih-proof-panel ih-run-panel" aria-label="Answer standard">
        <span className="ih-proof-icon" aria-hidden="true">
          <FileCheck2 size={18} />
        </span>
        <p>Answer standard</p>
        <strong>Sources first</strong>
        <span className="ih-proof-label">Every answer can be checked against its filing</span>
        <ol>
          <li>
            <CheckCircle2 size={13} aria-hidden="true" /> Identify the company and as-of date
          </li>
          <li>
            <CheckCircle2 size={13} aria-hidden="true" /> Rank the most relevant passages
          </li>
          <li>
            <CheckCircle2 size={13} aria-hidden="true" /> Check citations or return no answer
          </li>
        </ol>
      </aside>
    </div>
  );
}
