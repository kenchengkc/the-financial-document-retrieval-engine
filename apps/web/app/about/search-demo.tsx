"use client";

import {
  ArrowRight,
  CheckCircle2,
  FileText,
  LoaderCircle,
  Lock,
  MousePointer2,
  ScanSearch,
  Search,
  ShieldCheck,
  Table2,
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

type Source = { ticker: string; form: string; section: string; score: string };
type Issuer = { ticker: string; name: string; score: string };
type FunnelRow = { label: string; value: string; width: number };

type Scene = {
  tab: string;
  icon: typeof Search;
  query: string;
  ticker: string;
  form: string;
  date: string;
  answer: string;
  confidence: number;
  latency: string;
  sources: Source[];
  issuers?: Issuer[];
  funnel: FunnelRow[];
};

// Funnel counts mirror the live console's retrieval funnel: the indexed corpus,
// hybrid candidates, the reranked shortlist, and what survived citation
// verification. The abstention scene collapses to zero, showing the gate at work.
const SCENES: Scene[] = [
  {
    tab: "Cited answer",
    icon: Search,
    query:
      "In its latest 10-K, what significant risks and uncertainties does Apple associate with changes or additions to its supply chain?",
    ticker: "AAPL",
    form: "10-K",
    date: "2025-10-31",
    answer:
      "Changes or additions to the Company's supply chain require considerable time and resources and involve significant risks and uncertainties, including exposure to additional regulatory and operational risks.",
    confidence: 89,
    latency: "3.9 s",
    sources: [
      { ticker: "AAPL", form: "10-K", section: "Risk Factors", score: "0.820" },
      { ticker: "AAPL", form: "10-K", section: "Risk Factors", score: "0.652" },
    ],
    funnel: [
      { label: "Indexed chunks", value: "2.71M", width: 100 },
      { label: "Hybrid candidates", value: "240", width: 46 },
      { label: "Reranked", value: "8", width: 20 },
      { label: "Cited", value: "2", width: 9 },
    ],
  },
  {
    tab: "Typed facts",
    icon: Table2,
    query: "What did META report for earnings last quarter?",
    ticker: "META",
    form: "10-Q",
    date: "2026-04-30",
    answer:
      "Net income was $26.77 billion, with diluted earnings per share of $10.44 for the three months ended March 31, 2026.",
    confidence: 67,
    latency: "1.3 s",
    sources: [
      { ticker: "META", form: "10-Q", section: "MD&A", score: "0.648" },
      { ticker: "META", form: "10-Q", section: "Financial Statements", score: "0.611" },
    ],
    funnel: [
      { label: "Indexed chunks", value: "2.71M", width: 100 },
      { label: "Hybrid candidates", value: "240", width: 46 },
      { label: "Reranked", value: "8", width: 20 },
      { label: "Cited", value: "2", width: 9 },
    ],
  },
  {
    tab: "Thematic scan",
    icon: ScanSearch,
    query: "Scan the S&P 500 for data center capacity constraints",
    ticker: "S&P 500",
    form: "cross-sectional",
    date: "",
    answer: "Strongest passage per issuer, capped to one hit each so no filer dominates.",
    confidence: 0,
    latency: "4.1 s",
    sources: [],
    issuers: [
      { ticker: "DLR", name: "Digital Realty", score: "0.61" },
      { ticker: "EQIX", name: "Equinix", score: "0.58" },
      { ticker: "VRT", name: "Vertiv", score: "0.55" },
      { ticker: "MSFT", name: "Microsoft", score: "0.53" },
      { ticker: "GEV", name: "GE Vernova", score: "0.51" },
      { ticker: "ETN", name: "Eaton", score: "0.49" },
    ],
    funnel: [
      { label: "Indexed chunks", value: "2.71M", width: 100 },
      { label: "Hybrid candidates", value: "480", width: 52 },
      { label: "Issuer-diversified", value: "6", width: 18 },
      { label: "One hit each", value: "6", width: 18 },
    ],
  },
  {
    tab: "Abstention",
    icon: ShieldCheck,
    query: "What will NVIDIA's stock price be next quarter?",
    ticker: "N/A",
    form: "abstained",
    date: "",
    answer: "FDRE does not forecast securities prices or provide trading recommendations.",
    confidence: 0,
    latency: "0.4 s",
    sources: [],
    funnel: [
      { label: "Indexed chunks", value: "2.71M", width: 100 },
      { label: "Hybrid candidates", value: "0", width: 4 },
      { label: "Evidence gate", value: "held", width: 4 },
      { label: "Cited", value: "0", width: 4 },
    ],
  },
];

export function SearchDemo() {
  const [scene, setScene] = useState(0);
  const [phase, setPhase] = useState<Phase>("typing");
  const [typed, setTyped] = useState(0);
  const reduced = usePrefersReducedMotion();
  const current = SCENES[scene];
  const abstained = current.form === "abstained";
  const scan = Boolean(current.issuers);

  function jumpTo(index: number) {
    setScene(index);
    setTyped(0);
    setPhase("typing");
  }

  // type the query out, then move the cursor to the button
  useEffect(() => {
    if (reduced || phase !== "typing") return;
    if (typed >= current.query.length) {
      const hold = window.setTimeout(() => setPhase("clicking"), 500);
      return () => window.clearTimeout(hold);
    }
    const tick = window.setTimeout(() => setTyped((value) => value + 1), 40);
    return () => window.clearTimeout(tick);
  }, [reduced, phase, typed, current.query.length]);

  // cursor glides to the button and clicks -> thinking
  useEffect(() => {
    if (reduced || phase !== "clicking") return;
    const timer = window.setTimeout(() => setPhase("thinking"), 1050);
    return () => window.clearTimeout(timer);
  }, [reduced, phase]);

  // thinking -> answer
  useEffect(() => {
    if (reduced || phase !== "thinking") return;
    const timer = window.setTimeout(() => setPhase("answer"), 2100);
    return () => window.clearTimeout(timer);
  }, [reduced, phase]);

  // answer -> advance to next scene
  useEffect(() => {
    if (reduced || phase !== "answer") return;
    const timer = window.setTimeout(() => {
      setScene((value) => (value + 1) % SCENES.length);
      setTyped(0);
      setPhase("typing");
    }, 5200);
    return () => window.clearTimeout(timer);
  }, [reduced, phase]);

  const shownQuery = reduced ? current.query : current.query.slice(0, typed);
  const showAnswer = reduced || phase === "answer";
  const showThinking = !reduced && phase === "thinking";
  const showFunnel = showThinking || showAnswer;
  const clicking = phase === "clicking";

  return (
    <div className="bdemo-wrap">
      <div className="bdemo-tabs" role="tablist" aria-label="Demo scenarios">
        {SCENES.map((candidate, index) => {
          const Icon = candidate.icon;
          return (
            <button
              key={candidate.tab}
              type="button"
              role="tab"
              aria-selected={index === scene}
              className={index === scene ? "on" : undefined}
              onClick={() => jumpTo(index)}
            >
              <Icon size={13} aria-hidden="true" />
              {candidate.tab}
            </button>
          );
        })}
      </div>

      <div className={`bdemo${clicking ? " clicking" : ""}`} aria-hidden="true">
        <div className="bdemo-bar">
          <span className="bdemo-dots">
            <i />
            <i />
            <i />
          </span>
          <span className="bdemo-url">
            <Lock size={11} aria-hidden="true" />
            thefdre.com
          </span>
          <span className="bdemo-live">
            <span className="bdemo-live-dot" />
            live retrieval
          </span>
        </div>

        <div className="bdemo-body">
          <div className="bdemo-search">
            <Search size={17} aria-hidden="true" />
            <span className="bdemo-typed">
              {shownQuery}
              {!showAnswer && <span className="bdemo-caret" />}
            </span>
            <span className={`bdemo-go${showThinking ? " busy" : ""}`}>
              {showThinking ? (
                <LoaderCircle className="spin" size={14} />
              ) : (
                <ArrowRight size={14} />
              )}
            </span>
            {clicking && (
              <span className="bdemo-cursor" key={scene}>
                <MousePointer2 size={18} aria-hidden="true" />
              </span>
            )}
          </div>

          {showFunnel && (
            <div className={`bdemo-funnel${abstained ? " abstain" : ""}`} key={`f-${scene}`}>
              {current.funnel.map((row, index) => (
                <div className="bdemo-funnel-row" key={row.label}>
                  <span className="bdemo-funnel-label">{row.label}</span>
                  <span className="bdemo-funnel-track">
                    <span
                      className="bdemo-funnel-fill"
                      style={{ width: `${row.width}%`, animationDelay: `${index * 0.22}s` }}
                    />
                  </span>
                  <span className="bdemo-funnel-value">{row.value}</span>
                </div>
              ))}
            </div>
          )}

          {showAnswer && (
            <div className={`bdemo-result${abstained ? " abstain" : ""}`} key={scene}>
              {abstained ? (
                <>
                  <div className="bdemo-meta abstain">
                    <ShieldCheck size={14} aria-hidden="true" />
                    Deliberate abstention
                  </div>
                  <p className="bdemo-answer">{current.answer}</p>
                  <div className="bdemo-foot">
                    <span>Evidence gate held · no citation fabricated</span>
                    <span>{current.latency}</span>
                  </div>
                </>
              ) : scan ? (
                <>
                  <div className="bdemo-meta">
                    <CheckCircle2 size={14} aria-hidden="true" />
                    {current.issuers?.length} issuers surfaced
                  </div>
                  <p className="bdemo-answer">{current.answer}</p>
                  <div className="bdemo-issuers">
                    {current.issuers?.map((issuer) => (
                      <span key={issuer.ticker} className="bdemo-issuer">
                        <strong>{issuer.ticker}</strong> {issuer.name}
                        <em>{issuer.score}</em>
                      </span>
                    ))}
                  </div>
                  <div className="bdemo-foot">
                    <span>
                      <ScanSearch size={12} aria-hidden="true" />
                      {current.ticker} · {current.form}
                    </span>
                    <span>{current.latency}</span>
                  </div>
                </>
              ) : (
                <>
                  <div className="bdemo-meta">
                    <CheckCircle2 size={14} aria-hidden="true" />
                    Citation verified
                    <span className="bdemo-conf">{current.confidence}% confidence</span>
                  </div>
                  <p className="bdemo-answer">{current.answer}</p>
                  <div className="bdemo-sources">
                    {current.sources.map((source) => (
                      <span key={source.section} className="bdemo-source">
                        <strong>{source.ticker}</strong> {source.form} · {source.section}
                        <em>{source.score}</em>
                      </span>
                    ))}
                  </div>
                  <div className="bdemo-foot">
                    <span>
                      <FileText size={12} aria-hidden="true" />
                      {current.ticker} · {current.form} · {current.date}
                    </span>
                    <span>{current.latency}</span>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
