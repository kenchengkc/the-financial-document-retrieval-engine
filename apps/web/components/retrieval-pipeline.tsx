"use client";

import { FileText, Filter, Search, ListFilter, ShieldCheck, MessageSquareText, Pause, Play, ArrowRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import styles from "./retrieval-pipeline.module.css";

const stages = [
  { title: "Identify", icon: Filter, heading: "Start with the right scope", detail: "Resolve the company and apply the information cutoff before searching.", label: "Company + as-of date" },
  { title: "Search", icon: Search, heading: "Find the source passages", detail: "Search eligible filings with both keyword and semantic retrieval.", label: "Keyword + semantic search" },
  { title: "Rank", icon: ListFilter, heading: "Bring relevant evidence forward", detail: "Order candidate passages by relevance to the question.", label: "Relevant passages first" },
  { title: "Validate", icon: ShieldCheck, heading: "Check the citation trail", detail: "Verify the supporting source text before returning an answer.", label: "Source text + citation" },
  { title: "Answer", icon: MessageSquareText, heading: "Return evidence, or abstain", detail: "Present a cited answer. If the evidence does not support it, say so.", label: "Cited answer or abstention" },
];

export function RetrievalPipeline() {
  const root = useRef<HTMLDivElement>(null);
  const [step, setStep] = useState(0);
  const [paused, setPaused] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(true);
  const [visible, setVisible] = useState(false);
  const [tabVisible, setTabVisible] = useState(true);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const updateMotion = () => setReducedMotion(media.matches);
    const updateVisibility = () => setTabVisible(!document.hidden);
    updateMotion();
    updateVisibility();
    media.addEventListener("change", updateMotion);
    document.addEventListener("visibilitychange", updateVisibility);
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), { threshold: 0.15 });
    if (root.current) observer.observe(root.current);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", updateMotion);
      document.removeEventListener("visibilitychange", updateVisibility);
    };
  }, []);

  const playing = !paused && !reducedMotion && visible && tabVisible;
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => setStep((current) => (current + 1) % stages.length), 3200);
    return () => window.clearInterval(timer);
  }, [playing]);

  const stage = stages[step];
  const Icon = stage.icon;
  return (
    <div ref={root} className={styles.pipeline} data-playing={playing} data-step={step} aria-label="Retrieval pipeline illustration">
      <div className={styles.toolbar}>
        <span><span className={styles.dot} /> How a question becomes evidence</span>
        <div className={styles.controls}>
          <span>Illustrative walkthrough</span>
          {!reducedMotion && (
            <button type="button" onClick={() => setPaused((value) => !value)} aria-label={paused ? "Play pipeline animation" : "Pause pipeline animation"}>
              {paused ? <Play size={14} /> : <Pause size={14} />} {paused ? "Play" : "Pause"}
            </button>
          )}
        </div>
      </div>
      <div className={styles.scene}>
        <div className={styles.question}>
          <span className={styles.eyebrow}>Research question</span>
          <p>What changed in the company’s risk disclosures?</p>
          <div className={styles.tags}><span>Company</span><span>As-of date</span></div>
        </div>
        <div className={styles.connector} aria-hidden="true"><span /><ArrowRight size={16} /></div>
        <div className={styles.workspace} data-phase={step} aria-hidden="true">
          <div className={styles.documents}>
            {[0, 1, 2].map((index) => (
              <div className={styles.document} key={index}>
                <FileText size={18} /><small>{["10-K", "10-Q", "10-K"][index]}</small>
                <i /><i /><i /><i />
                <span className={styles.highlight} />
                <span className={styles.check}><ShieldCheck size={17} /></span>
              </div>
            ))}
          </div>
          <div className={styles.scan} />
          <div className={styles.sourceLabel}><Icon size={14} />{stage.label}</div>
        </div>
        <div className={styles.connector} aria-hidden="true"><span /><ArrowRight size={16} /></div>
        <div className={styles.explanation}>
          <span className={styles.eyebrow}>Step {String(step + 1).padStart(2, "0")} / 05</span>
          <h3>{stage.heading}</h3>
          <p>{stage.detail}</p>
        </div>
      </div>
      <ol className={styles.stages} aria-label="Pipeline stages">
        {stages.map((item, index) => (
          <li key={item.title}>
            <button type="button" aria-label={`Show ${item.title} stage`} aria-current={step === index ? "step" : undefined} onClick={() => { setStep(index); setPaused(true); }}>
              <span className={styles.number}>{String(index + 1).padStart(2, "0")}</span>
              <item.icon size={16} aria-hidden="true" /><strong>{item.title}</strong>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
