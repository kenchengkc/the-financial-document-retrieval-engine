"use client";

import {
  ArrowRight,
  CheckCircle2,
  FileText,
  LoaderCircle,
  Lock,
  MousePointer2,
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

type Source = { ticker: string; form: string; section: string; score: string };

type Scene = {
  query: string;
  ticker: string;
  form: string;
  date: string;
  answer: string;
  confidence: number;
  latency: string;
  sources: Source[];
};

const SCENES: Scene[] = [
  {
    query: "What did Apple say about supply chain risk in its latest 10-K?",
    ticker: "AAPL",
    form: "10-K",
    date: "2025-10-31",
    answer:
      "Although most components essential to the Company's business are generally available from multiple sources, certain components are currently obtained from single or limited sources.",
    confidence: 57,
    latency: "0.9 s",
    sources: [
      { ticker: "AAPL", form: "10-K", section: "Risk Factors", score: "0.574" },
      { ticker: "AAPL", form: "10-K", section: "Business", score: "0.512" },
    ],
  },
  {
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
  },
  {
    query: "What will NVIDIA's stock price be next quarter?",
    ticker: "—",
    form: "abstained",
    date: "",
    answer:
      "FDRE does not forecast securities prices or provide trading recommendations.",
    confidence: 0,
    latency: "0.4 s",
    sources: [],
  },
];

export function SearchDemo() {
  const [scene, setScene] = useState(0);
  const [phase, setPhase] = useState<Phase>("typing");
  const [typed, setTyped] = useState(0);
  const reduced = usePrefersReducedMotion();
  const current = SCENES[scene];
  const abstained = current.sources.length === 0;

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
    const timer = window.setTimeout(() => setPhase("answer"), 1500);
    return () => window.clearTimeout(timer);
  }, [reduced, phase]);

  // answer -> advance to next scene
  useEffect(() => {
    if (reduced || phase !== "answer") return;
    const timer = window.setTimeout(() => {
      setScene((value) => (value + 1) % SCENES.length);
      setTyped(0);
      setPhase("typing");
    }, 4400);
    return () => window.clearTimeout(timer);
  }, [reduced, phase]);

  const shownQuery = reduced ? current.query : current.query.slice(0, typed);
  const showAnswer = reduced || phase === "answer";
  const showThinking = !reduced && phase === "thinking";
  const clicking = phase === "clicking";

  return (
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
            {showThinking ? <LoaderCircle className="spin" size={14} /> : <ArrowRight size={14} />}
          </span>
          {clicking && (
            <span className="bdemo-cursor" key={scene}>
              <MousePointer2 size={18} aria-hidden="true" />
            </span>
          )}
        </div>

        {showThinking && (
          <div className="bdemo-stages">
            {["Resolve issuer", "Retrieve", "Rerank", "Verify citations"].map((stage, index) => (
              <span key={stage} style={{ animationDelay: `${index * 0.18}s` }}>
                {stage}
              </span>
            ))}
          </div>
        )}

        {showAnswer && (
          <div className={`bdemo-result${abstained ? " abstain" : ""}`} key={scene}>
            {abstained ? (
              <>
                <div className="bdemo-meta abstain">
                  <CheckCircle2 size={14} aria-hidden="true" />
                  Deliberate abstention
                </div>
                <p className="bdemo-answer">{current.answer}</p>
                <div className="bdemo-foot">
                  <span>Evidence gate held · no citation fabricated</span>
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
  );
}
