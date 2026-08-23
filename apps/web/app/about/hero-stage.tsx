import { ArrowDown, CheckCircle2, Database, FileCheck2 } from "lucide-react";

export function HeroStage() {
  return (
    <div className="ih-stage">
      <aside className="ih-panel ih-proof-panel ih-corpus-panel" aria-label="Corpus scope">
        <span className="ih-proof-icon" aria-hidden="true">
          <Database size={18} />
        </span>
        <p>Corpus scope</p>
        <strong>499 / 500</strong>
        <span className="ih-proof-label">S&amp;P 500 primary tickers indexed</span>
        <ul>
          <li>SEC 10-K and 10-Q filings</li>
          <li>Current constituents; survivorship-biased</li>
          <li>Live coverage and quality checks below</li>
        </ul>
      </aside>

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

      <aside className="ih-panel ih-proof-panel ih-run-panel" aria-label="Answer contract">
        <span className="ih-proof-icon" aria-hidden="true">
          <FileCheck2 size={18} />
        </span>
        <p>Answer contract</p>
        <strong>Evidence first</strong>
        <span className="ih-proof-label">Every supported claim is reviewable against its filing</span>
        <ol>
          <li>
            <CheckCircle2 size={13} aria-hidden="true" /> Resolve issuer and time boundary
          </li>
          <li>
            <CheckCircle2 size={13} aria-hidden="true" /> Rerank retrieved passages
          </li>
          <li>
            <CheckCircle2 size={13} aria-hidden="true" /> Verify citation or abstain
          </li>
        </ol>
      </aside>
    </div>
  );
}
