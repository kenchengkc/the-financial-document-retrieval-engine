const features = [
  {
    icon: "▤",
    title: "Layout-aware parsing",
    body: "SEC HTML and PDFs parsed into typed elements — titles, sections, text blocks, and tables — with reading order preserved.",
  },
  {
    icon: "⌗",
    title: "Table-aware indexing",
    body: "Tables aren't flattened into noise. Each becomes a markdown chunk, a summary chunk, and row/column metadata.",
  },
  {
    icon: "⇄",
    title: "Hybrid retrieval",
    body: "Dense embeddings + PostgreSQL full-text search, score-normalized and merged, then reranked with a cross-encoder.",
  },
  {
    icon: "✓",
    title: "Citation verification",
    body: "Every factual claim must cite a retrieved chunk, and citation text is checked for overlap. No hallucinated sources.",
  },
  {
    icon: "⊘",
    title: "Answer abstention",
    body: "When evidence is below threshold or verification fails, FDRE declines to answer instead of guessing.",
  },
  {
    icon: "◉",
    title: "Bounded orchestration",
    body: "A typed, inspectable LangGraph workflow — no recursive loops. Every run is auditable from query to output.",
  },
];

const evalRows = [
  { v: "Dense only", r: "0.63", mrr: "0.58", ndcg: "0.61", tr: "0.44", best: false },
  { v: "Sparse only", r: "0.63", mrr: "0.60", ndcg: "0.59", tr: "0.52", best: false },
  { v: "Hybrid", r: "0.79", mrr: "0.74", ndcg: "0.76", tr: "0.66", best: false },
  { v: "Hybrid + reranker", r: "0.86", mrr: "0.82", ndcg: "0.81", tr: "0.78", best: true },
];

export default function Home() {
  return (
    <>
      <header className="nav">
        <div className="wrap" style={{ display: "flex", alignItems: "center", width: "100%", gap: 22 }}>
          <div className="brand">
            <div className="logo">F</div>
            <div>
              <div className="name">FDRE</div>
              <div className="sub">Financial Document Retrieval Engine</div>
            </div>
          </div>
          <div className="links">
            <a href="#why">Why</a>
            <a href="#how">Architecture</a>
            <a href="#evals">Evals</a>
            <a href="/demo.html" className="btn ghost" style={{ marginLeft: 6 }}>
              Live demo →
            </a>
          </div>
        </div>
      </header>

      <main className="wrap">
        {/* HERO */}
        <section className="hero">
          <div className="eyebrow">
            <span className="dot" /> Retrieval engine · not a chatbot
          </div>
          <h1>
            Search, rank, and <span className="grad">verify evidence</span> across SEC filings.
          </h1>
          <p className="lead">
            FDRE ingests SEC filings, parses document structure, indexes text and tables, and
            retrieves cited evidence across filings and structured company facts.
          </p>
          <p className="kicker">
            Not a chatbot over documents. A retrieval engine with <b>citations</b>, <b>evals</b>, and{" "}
            <b>abstention</b> — built so answer quality comes from context engineering, not prompts.
          </p>
          <div className="cta-row">
            <a href="/demo.html" className="btn">
              Explore the evidence viewer →
            </a>
            <a
              href="https://github.com/"
              className="btn ghost"
              target="_blank"
              rel="noreferrer"
            >
              View source
            </a>
          </div>
        </section>

        {/* WHY */}
        <section className="block" id="why">
          <div className="sec-label">The thesis</div>
          <h2>Why naive RAG fails on filings</h2>
          <p className="intro">
            Chunk-and-embed pipelines collapse on 10-Ks: they shred tables, ignore section
            structure, retrieve loosely-relevant passages, and confidently answer even when the
            evidence isn&apos;t there. FDRE is built around the opposite defaults.
          </p>
          <div className="compare">
            <div className="card fail">
              <h3>✗ Naive &quot;chat with PDFs&quot;</h3>
              <ul>
                <li><span className="m">—</span> Tables flattened into unreadable token soup</li>
                <li><span className="m">—</span> No section or filing-type awareness</li>
                <li><span className="m">—</span> Single dense retriever, no reranking</li>
                <li><span className="m">—</span> Answers with no verifiable citation</li>
                <li><span className="m">—</span> Hallucinates rather than abstaining</li>
                <li><span className="m">—</span> No way to measure retrieval quality</li>
              </ul>
            </div>
            <div className="card fix">
              <h3>✓ FDRE</h3>
              <ul>
                <li><span className="m">+</span> Tables kept as structured, summarized chunks</li>
                <li><span className="m">+</span> Ticker / form / section filters from the query</li>
                <li><span className="m">+</span> Hybrid dense + sparse, then cross-encoder rerank</li>
                <li><span className="m">+</span> Every claim grounded in a verified citation</li>
                <li><span className="m">+</span> Abstains when evidence is below threshold</li>
                <li><span className="m">+</span> Recall@k, MRR, nDCG measured per variant</li>
              </ul>
            </div>
          </div>
        </section>

        {/* HOW */}
        <section className="block" id="how">
          <div className="sec-label">Under the hood</div>
          <h2>A bounded retrieval pipeline</h2>
          <p className="intro">
            Deterministic preprocessing routes the query before any model runs. Retrieval, merging,
            reranking, gating, and citation verification all happen before a single answer token —
            and every step is traced.
          </p>
          <div className="pipe" style={{ marginBottom: 40 }}>
            <span className="node hl">preprocess</span>
            <span className="arr">→</span>
            <span className="node">route</span>
            <span className="arr">→</span>
            <span className="node hl">hybrid retrieve</span>
            <span className="arr">→</span>
            <span className="node">rerank</span>
            <span className="arr">→</span>
            <span className="node hl">gate</span>
            <span className="arr">→</span>
            <span className="node">generate</span>
            <span className="arr">→</span>
            <span className="node hl">verify citations</span>
            <span className="arr">→</span>
            <span className="node">answer / abstain</span>
          </div>
          <div className="features">
            {features.map((f) => (
              <div className="feat" key={f.title}>
                <div className="ic">{f.icon}</div>
                <h4>{f.title}</h4>
                <p>{f.body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* EVALS */}
        <section className="block" id="evals">
          <div className="sec-label">Measured, not vibes</div>
          <h2>Retrieval quality is the product</h2>
          <p className="intro">
            FDRE ships an evaluation harness that scores every retriever variant on a labelled gold
            set. Reranking lifts Recall@5 by 7 points and table recall by 12 over plain hybrid.
          </p>
          <div className="tablewrap">
            <table className="evtable">
              <thead>
                <tr>
                  <th>Variant</th>
                  <th>Recall@5</th>
                  <th>MRR</th>
                  <th>nDCG@10</th>
                  <th>Table Recall@5</th>
                </tr>
              </thead>
              <tbody>
                {evalRows.map((row) => (
                  <tr key={row.v} className={row.best ? "best" : undefined}>
                    <td>
                      {row.v}
                      {row.best && <span className="badge">BEST</span>}
                    </td>
                    <td>{row.r}</td>
                    <td>{row.mrr}</td>
                    <td>{row.ndcg}</td>
                    <td>{row.tr}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* CTA */}
        <section className="ctaband">
          <h2>Inspect the evidence yourself</h2>
          <p>
            Ask a question, see the ranked chunks with dense / sparse / hybrid / rerank scores, the
            verified citations behind every claim, and the full graph trace.
          </p>
          <div className="cta-row center">
            <a href="/demo.html" className="btn">
              Open the live demo →
            </a>
          </div>
        </section>

        <footer>
          <div className="brand">
            <div className="logo" style={{ width: 24, height: 24, fontSize: 12 }}>
              F
            </div>
            <span>FDRE · Financial Document Retrieval Engine</span>
          </div>
          <span className="right">thefdre.com</span>
        </footer>
      </main>
    </>
  );
}
