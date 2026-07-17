"use client";

import {
  ArrowRight,
  Braces,
  CheckCircle2,
  FileDiff,
  FileText,
  Layers3,
  LineChart,
  LoaderCircle,
  MessageSquareText,
  MousePointer2,
  ScanSearch,
  Search,
} from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";

function usePrefersReducedMotion() {
  return useSyncExternalStore(
    (notify) => {
      const query = window.matchMedia("(prefers-reduced-motion: reduce)");
      query.addEventListener("change", notify);
      return () => query.removeEventListener("change", notify);
    },
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => false,
  );
}

type Phase = "typing" | "clicking" | "thinking" | "answer";
type ModeId = "ask" | "retrieve" | "screen" | "signals";

type Scene = {
  id: ModeId;
  label: string;
  hint: string;
  icon: typeof Search;
  eyebrow: string;
  title: string;
  lede: string;
  query: string;
  action: string;
  processing: string;
  stages: string[];
  typeQuery?: boolean;
};

const SCENES: Scene[] = [
  {
    id: "ask",
    label: "Ask",
    hint: "Cited answers from filings",
    icon: MessageSquareText,
    eyebrow: "Cited answers from filings",
    title: "Ask",
    lede: "Retrieve, rerank, and verify filing evidence before answering.",
    query:
      "In its latest 10-K, what risks does Apple associate with changes to its supply chain?",
    action: "Ask",
    processing: "Searching indexed SEC filings",
    stages: ["Resolve issuer", "Retrieve evidence", "Rerank sources", "Verify citations"],
    typeQuery: true,
  },
  {
    id: "retrieve",
    label: "Retrieve",
    hint: "Hybrid search, point-in-time",
    icon: Search,
    eyebrow: "Normalized XBRL fundamentals",
    title: "Query reported financials",
    lede: "Pull standardized filing values with an explicit information cutoff.",
    query: "META",
    action: "Query facts",
    processing: "Resolving point-in-time facts",
    stages: ["Resolve issuer", "Apply cutoff", "Normalize values", "Retain provenance"],
    typeQuery: true,
  },
  {
    id: "screen",
    label: "Screen",
    hint: "Cross-sectional theme scan",
    icon: ScanSearch,
    eyebrow: "Cross-sectional theme scan",
    title: "Screen",
    lede: "Rank issuers by the strength of their disclosure evidence.",
    query: "data center capacity constraints",
    action: "Scan",
    processing: "Scanning the filing universe",
    stages: ["Parse theme", "Search corpus", "Diversify issuers", "Rank results"],
    typeQuery: true,
  },
  {
    id: "signals",
    label: "Signals",
    hint: "Event-study backtests",
    icon: LineChart,
    eyebrow: "Event-study backtests",
    title: "Signals",
    lede: "Test filing-behavior signals with leakage-safe panels and adjusted inference.",
    query: "Share issuance → returns",
    action: "Run study",
    processing: "Replaying the point-in-time study",
    stages: ["Build panel", "Join forward returns", "Bootstrap inference", "Adjust p-values"],
  },
];

const RETRIEVE_TOOLS = [
  { label: "Search text", detail: "Rank passages", icon: Search },
  { label: "Compare filings", detail: "Review changes", icon: FileDiff },
  { label: "Financial facts", detail: "Query values", icon: Braces },
  { label: "Build dataset", detail: "Export rows", icon: Layers3 },
];

function DemoCursor({ signal = false }: { signal?: boolean }) {
  return (
    <span className={`bdemo-cursor${signal ? " signal" : ""}`}>
      <MousePointer2 size={17} aria-hidden="true" />
    </span>
  );
}

function QueryControl({
  scene,
  shownQuery,
  showThinking,
  clicking,
  showCaret,
}: {
  scene: Scene;
  shownQuery: string;
  showThinking: boolean;
  clicking: boolean;
  showCaret: boolean;
}) {
  if (scene.id === "retrieve") {
    return (
      <>
        <div className="bdemo-subtools">
          {RETRIEVE_TOOLS.map((tool) => {
            const Icon = tool.icon;
            return (
              <span key={tool.label} className={tool.label === "Financial facts" ? "on" : undefined}>
                <Icon size={12} aria-hidden="true" />
                <span>
                  <strong>{tool.label}</strong>
                  <small>{tool.detail}</small>
                </span>
              </span>
            );
          })}
        </div>
        <div className="bdemo-fact-form">
          <span className="bdemo-field ticker">
            <small>Tickers</small>
            <strong>
              {shownQuery}
              {showCaret && <i className="bdemo-caret" />}
            </strong>
          </span>
          <span className="bdemo-field">
            <small>Metric</small>
            <strong>All canonical metrics</strong>
          </span>
          <span className="bdemo-field">
            <small>Value version</small>
            <strong>Original filing value</strong>
          </span>
          <span className="bdemo-field cutoff">
            <small>Information cutoff</small>
            <strong>2026-04-30</strong>
          </span>
          <span className={`bdemo-action${showThinking ? " busy" : ""}`}>
            {showThinking ? <LoaderCircle className="spin" size={13} /> : <ArrowRight size={13} />}
            {showThinking ? "Loading" : scene.action}
          </span>
          {clicking && <DemoCursor />}
        </div>
      </>
    );
  }

  if (scene.id === "signals") {
    return (
      <>
        <div className="bdemo-view-switch">
          <span className="on">Study</span>
          <span>Monitor</span>
          <span>Audit</span>
        </div>
        <div className="bdemo-study-tabs">
          <span>
            <strong>Earnings quality → returns</strong>
            <small>No edge</small>
          </span>
          <span className={`on${clicking ? " press" : ""}`}>
            <strong>{shownQuery}</strong>
            <small>1/3 horizons significant</small>
            {clicking && <DemoCursor signal />}
          </span>
          <span>
            <strong>Asset growth → returns</strong>
            <small>No edge</small>
          </span>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="bdemo-query">
        {scene.id === "screen" ? (
          <ScanSearch size={16} aria-hidden="true" />
        ) : (
          <Search size={16} aria-hidden="true" />
        )}
        <span className="bdemo-typed">
          {shownQuery}
          {showCaret && <i className="bdemo-caret" />}
        </span>
        <span className={`bdemo-action${showThinking ? " busy" : ""}`}>
          {showThinking ? <LoaderCircle className="spin" size={13} /> : <ArrowRight size={13} />}
          {showThinking ? (scene.id === "screen" ? "Scanning" : "Retrieving") : scene.action}
        </span>
        {clicking && <DemoCursor />}
      </div>
      {scene.id === "ask" && (
        <div className="bdemo-examples">
          <span className="on"><strong>AAPL · text</strong> Supply-chain changes</span>
          <span><strong>META · earnings</strong> Latest quarter</span>
          <span className="abstain"><strong>No forecasts</strong> Unsupported request</span>
        </div>
      )}
      {scene.id === "screen" && (
        <div className="bdemo-screen-scope">
          <span><strong>Universe</strong> S&amp;P 500 · 498 issuers</span>
          <span><strong>Top issuers</strong> 6</span>
        </div>
      )}
    </>
  );
}

function ProcessingState({ scene }: { scene: Scene }) {
  return (
    <div className="bdemo-processing">
      <div className="bdemo-processing-head">
        <LoaderCircle className="spin" size={15} aria-hidden="true" />
        <strong>{scene.processing}</strong>
        <span>72%</span>
      </div>
      <span className="bdemo-progress"><i /></span>
      <ol>
        {scene.stages.map((stage, index) => (
          <li key={stage} className={index < 2 ? "done" : index === 2 ? "active" : undefined}>
            <span>{index < 2 ? "✓" : index + 1}</span>
            {stage}
          </li>
        ))}
      </ol>
    </div>
  );
}

function AskResult({ scene }: { scene: Scene }) {
  const funnel = [
    { label: "retrieved", value: "240", width: 100 },
    { label: "reranked", value: "8", width: 42 },
    { label: "gate passed", value: "4", width: 22 },
    { label: "cited", value: "2", width: 11 },
  ];
  return (
    <div className="bdemo-ask-result bdemo-result-in">
      <div className="bdemo-answer-column">
        <article className="bdemo-answer-card">
          <div className="bdemo-answer-meta">
            <CheckCircle2 size={13} aria-hidden="true" />
            Citation verified <span>· 3.9 s</span>
          </div>
          <p className="bdemo-answer-question">{scene.query}</p>
          <p className="bdemo-answer-copy">
            Changes or additions to the Company&apos;s supply chain require considerable time and
            resources and involve significant risks and uncertainties, including additional
            regulatory and operational risks.
          </p>
          <footer>
            <span><FileText size={11} aria-hidden="true" /> AAPL · 10-K · 2025-10-31</span>
            <span>run_9f42ac</span>
          </footer>
        </article>
        <div className="bdemo-source-title">
          <strong>Primary sources</strong>
          <span>2 passages · AAPL</span>
        </div>
        <div className="bdemo-evidence-row">
          <span>01</span>
          <strong>AAPL</strong>
          <span>10-K · 2025-10-31</span>
          <em>Item 1A · Risk Factors</em>
          <span className="cited"><CheckCircle2 size={11} /> cited</span>
          <span className="score">0.820</span>
        </div>
      </div>
      <aside className="bdemo-run-card">
        <h4><LineChart size={13} aria-hidden="true" /> Run summary</h4>
        <div className="bdemo-run-top">
          <div className="bdemo-ring" style={{ background: "conic-gradient(#6d3d63 89%, #e8ded9 0)" }}>
            <strong>89<small>%</small></strong>
          </div>
          <dl>
            <div><dt>Evidence gate</dt><dd className="ok">Passed</dd></div>
            <div><dt>Top rerank</dt><dd>0.820</dd></div>
            <div><dt>Latency</dt><dd>3.9 s</dd></div>
          </dl>
        </div>
        <div className="bdemo-run-funnel">
          {funnel.map((row, index) => (
            <div key={row.label}>
              <span>{row.label}</span>
              <i><b style={{ width: `${row.width}%`, animationDelay: `${index * 0.1}s` }} /></i>
              <strong>{row.value}</strong>
            </div>
          ))}
        </div>
        <div className="bdemo-routes">
          <span>resolve issuer</span><span>retrieve text</span><span>rerank</span><span>verify citations</span>
        </div>
      </aside>
    </div>
  );
}

function RetrieveResult() {
  return (
    <div className="bdemo-data-result bdemo-result-in">
      <div className="bdemo-statusbar">
        <span><strong>2</strong> reported facts</span>
        <span>originally reported values</span>
        <span className="ok"><CheckCircle2 size={11} /> source filing retained</span>
      </div>
      <div className="bdemo-table-wrap">
        <table>
          <thead>
            <tr><th>Issuer</th><th>Metric</th><th>Value</th><th>Period</th><th>Available</th><th>Source</th></tr>
          </thead>
          <tbody>
            <tr><td><strong>META</strong><small>10-Q</small></td><td>Net income<small>USD</small></td><td className="num">$26.77B</td><td>Q1 2026<small>2026-03-31</small></td><td>2026-04-30</td><td className="mono">0001326801…</td></tr>
            <tr><td><strong>META</strong><small>10-Q</small></td><td>Diluted EPS<small>USD / share</small></td><td className="num">$10.44</td><td>Q1 2026<small>2026-03-31</small></td><td>2026-04-30</td><td className="mono">0001326801…</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

const SCREEN_ISSUERS = [
  {
    rank: "01",
    ticker: "DLR",
    company: "Digital Realty",
    score: "0.610",
    copy: "Power availability and delivery timelines constrain new data-center capacity.",
  },
  {
    rank: "02",
    ticker: "EQIX",
    company: "Equinix",
    score: "0.580",
    copy: "Utility interconnection queues can delay expansion in high-demand markets.",
  },
  {
    rank: "03",
    ticker: "VRT",
    company: "Vertiv",
    score: "0.550",
    copy: "Lead times for power and thermal systems remain a capacity bottleneck.",
  },
  {
    rank: "04",
    ticker: "AMZN",
    company: "Amazon",
    score: "0.520",
    copy: "Power, land, and permitting constraints can delay planned cloud infrastructure.",
  },
  {
    rank: "05",
    ticker: "MSFT",
    company: "Microsoft",
    score: "0.490",
    copy: "Datacenter buildout depends on timely access to power and network capacity.",
  },
  {
    rank: "06",
    ticker: "GOOGL",
    company: "Alphabet",
    score: "0.470",
    copy: "AI infrastructure demand increases pressure on compute and energy availability.",
  },
];

function ScreenResult() {
  return (
    <div className="bdemo-screen-result bdemo-result-in">
      <div className="bdemo-ranked-head">
        <strong>Ranked issuers</strong>
        <span>6 of 498 · 4.1 s</span>
      </div>
      <div className="bdemo-issuer-grid">
        {SCREEN_ISSUERS.map((issuer) => (
          <article key={issuer.ticker}>
            <header>
              <span>{issuer.rank}</span>
              <div><strong>{issuer.ticker}</strong><small>{issuer.company}</small></div>
              <em>{issuer.score}</em>
            </header>
            <p>{issuer.copy}</p>
            <footer><span>10-K · Item 1A</span><strong>Open →</strong></footer>
          </article>
        ))}
      </div>
    </div>
  );
}

const SIGNAL_ROWS = [
  { horizon: "+1 week", sample: "n = 230", spread: "-0.75%", ic: "-0.045", verdict: "No edge", significant: false },
  { horizon: "+1 month", sample: "n = 228", spread: "-5.01%", ic: "-0.115", verdict: "Significant", significant: true },
  { horizon: "+1 quarter", sample: "n = 226", spread: "-5.08%", ic: "-0.042", verdict: "No edge", significant: false },
];

const QUINTILES = [
  { label: "Q1", value: "+3.24%", height: 64, positive: true },
  { label: "Q2", value: "-0.52%", height: 18, positive: false },
  { label: "Q3", value: "-0.16%", height: 10, positive: false },
  { label: "Q4", value: "+1.92%", height: 44, positive: true },
  { label: "Q5", value: "-1.77%", height: 40, positive: false },
];

function SignalsResult() {
  return (
    <div className="bdemo-signals-result bdemo-result-in">
      <div className="bdemo-signal-metrics">
        <div><strong>-5.01%</strong><span>Q5−Q1 · +1 month</span></div>
        <div><strong>0.024</strong><span>Adjusted p-value</span></div>
        <div><strong>240</strong><span>Filing events</span></div>
        <div><strong>Inverted</strong><span>Observed direction</span></div>
      </div>
      <div className="bdemo-signal-grid">
        <div className="bdemo-signal-table">
          <div className="head"><span>Horizon</span><span>Long-short</span><span>Rank IC</span><span>Verdict</span></div>
          {SIGNAL_ROWS.map((row) => (
            <div key={row.horizon} className={row.significant ? "significant" : undefined}>
              <span><strong>{row.horizon}</strong><small>{row.sample}</small></span>
              <span>{row.spread}</span>
              <span>{row.ic}</span>
              <span className={row.significant ? "sig" : "flat"}>{row.verdict}</span>
            </div>
          ))}
        </div>
        <div className="bdemo-quintiles">
          <strong>Quintile returns · +1 month</strong>
          <div>
            {QUINTILES.map((item, index) => (
              <span key={item.label}>
                <em>{item.value}</em>
                <i className={item.positive ? "positive" : "negative"} style={{ height: `${item.height}px`, animationDelay: `${index * 0.08}s` }} />
                <small>{item.label}</small>
              </span>
            ))}
          </div>
        </div>
      </div>
      <p className="bdemo-signal-note">
        Significant inversion: the largest issuers outperformed buyback names in this sample.
      </p>
    </div>
  );
}

function SceneResult({ scene }: { scene: Scene }) {
  if (scene.id === "ask") return <AskResult scene={scene} />;
  if (scene.id === "retrieve") return <RetrieveResult />;
  if (scene.id === "screen") return <ScreenResult />;
  return <SignalsResult />;
}

export function SearchDemo() {
  const [sceneIndex, setSceneIndex] = useState(0);
  const [phase, setPhase] = useState<Phase>("typing");
  const [typed, setTyped] = useState(0);
  const reduced = usePrefersReducedMotion();
  const current = SCENES[sceneIndex];

  function jumpTo(index: number) {
    setSceneIndex(index);
    setTyped(0);
    setPhase("typing");
  }

  useEffect(() => {
    if (reduced || phase !== "typing") return;
    if (!current.typeQuery) {
      const hold = window.setTimeout(() => setPhase("clicking"), 700);
      return () => window.clearTimeout(hold);
    }
    if (typed >= current.query.length) {
      const hold = window.setTimeout(() => setPhase("clicking"), 450);
      return () => window.clearTimeout(hold);
    }
    const step = current.query.length > 55 ? 2 : 1;
    const tick = window.setTimeout(
      () => setTyped((value) => Math.min(current.query.length, value + step)),
      34,
    );
    return () => window.clearTimeout(tick);
  }, [reduced, phase, typed, current]);

  useEffect(() => {
    if (reduced || phase !== "clicking") return;
    const timer = window.setTimeout(() => setPhase("thinking"), 900);
    return () => window.clearTimeout(timer);
  }, [reduced, phase]);

  useEffect(() => {
    if (reduced || phase !== "thinking") return;
    const timer = window.setTimeout(() => setPhase("answer"), 1750);
    return () => window.clearTimeout(timer);
  }, [reduced, phase]);

  useEffect(() => {
    if (reduced || phase !== "answer") return;
    const timer = window.setTimeout(() => {
      setSceneIndex((value) => (value + 1) % SCENES.length);
      setTyped(0);
      setPhase("typing");
    }, 5600);
    return () => window.clearTimeout(timer);
  }, [reduced, phase]);

  const shownQuery = reduced || !current.typeQuery ? current.query : current.query.slice(0, typed);
  const showAnswer = reduced || phase === "answer";
  const showThinking = !reduced && phase === "thinking";
  const clicking = !reduced && phase === "clicking";
  const showCaret = !reduced && phase === "typing" && Boolean(current.typeQuery);

  return (
    <div className="bdemo-wrap">
      <div className={`bdemo${clicking ? " clicking" : ""}`}>
        <div className="bdemo-mode-rail" role="tablist" aria-label="Research console modes">
          {SCENES.map((candidate, index) => {
            const Icon = candidate.icon;
            return (
              <button
                key={candidate.id}
                type="button"
                role="tab"
                aria-selected={index === sceneIndex}
                aria-controls="about-demo-panel"
                className={index === sceneIndex ? "on" : undefined}
                onClick={() => jumpTo(index)}
              >
                <span className="bdemo-mode-icon"><Icon size={15} aria-hidden="true" /></span>
                <span className="bdemo-mode-copy"><strong>{candidate.label}</strong><small>{candidate.hint}</small></span>
                <kbd aria-hidden="true">{index + 1}</kbd>
              </button>
            );
          })}
        </div>

        <div
          id="about-demo-panel"
          className="bdemo-body"
          role="tabpanel"
          aria-label={`${current.label} console replay`}
        >
          <header className="bdemo-panel-intro">
            <p className="eyebrow">{current.eyebrow}</p>
            <h3>{current.title}</h3>
            <p>{current.lede}</p>
          </header>

          <QueryControl
            scene={current}
            shownQuery={shownQuery}
            showThinking={showThinking}
            clicking={clicking}
            showCaret={showCaret}
          />

          {showThinking && <ProcessingState scene={current} />}
          {showAnswer && <SceneResult scene={current} />}
        </div>
      </div>
    </div>
  );
}
