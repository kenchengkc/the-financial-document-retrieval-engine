"use client";

import {
  ArrowUpRight,
  BarChart3,
  CheckCircle2,
  FileText,
  Search,
  TableProperties,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";

import styles from "./system-flow.module.css";

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

const STAGES = [
  {
    label: "Filing",
    detail: "Timestamped at the SEC",
    icon: FileText,
  },
  {
    label: "Parse",
    detail: "Text · tables · XBRL",
    icon: TableProperties,
  },
  {
    label: "Retrieve",
    detail: "Keyword + vector search",
    icon: Search,
  },
  {
    label: "Verify",
    detail: "PIT + source checks",
    icon: CheckCircle2,
  },
  {
    label: "Research",
    detail: "Answers · panels · studies",
    icon: BarChart3,
  },
] as const;

function FilingScene() {
  return (
    <div className={`${styles.scene} ${styles.filingScene}`}>
      <div className={styles.document}>
        <header>
          <span>SEC 10-K</span>
          <strong>AAPL</strong>
        </header>
        <div className={styles.docTitle}>Item 1A · Risk Factors</div>
        <i className={styles.lineWide} />
        <i className={styles.lineMid} />
        <i className={styles.lineWide} />
        <i className={styles.lineShort} />
        <div className={styles.scanLine} />
      </div>
      <div className={styles.timeStamp}>
        <small>available_at</small>
        <strong>2025-10-31 · 16:08:37</strong>
      </div>
    </div>
  );
}

function ParseScene() {
  return (
    <div className={`${styles.scene} ${styles.parseScene}`}>
      <div className={styles.parseSource}>
        <FileText size={24} aria-hidden="true" />
        <span>10-K</span>
      </div>
      <div className={styles.parseRail} aria-hidden="true">
        <i />
        <i />
        <i />
      </div>
      <div className={styles.fragments}>
        <div>
          <strong>Risk Factors</strong>
          <span>passages</span>
        </div>
        <div>
          <strong>Tables</strong>
          <span>structure</span>
        </div>
        <div>
          <strong>XBRL</strong>
          <span>facts</span>
        </div>
      </div>
    </div>
  );
}

function RetrieveScene() {
  return (
    <div className={`${styles.scene} ${styles.retrieveScene}`}>
      <div className={styles.queryBox}>
        <Search size={15} aria-hidden="true" />
        <span>supply chain risk</span>
      </div>
      <div className={styles.resultStack}>
        <div className={styles.bestResult}>
          <span>AAPL · Item 1A</span>
          <strong>0.820</strong>
        </div>
        <div>
          <span>AAPL · Business</span>
          <strong>0.611</strong>
        </div>
        <div>
          <span>AAPL · MD&amp;A</span>
          <strong>0.544</strong>
        </div>
      </div>
      <div className={styles.rankPulse} aria-hidden="true" />
    </div>
  );
}

function VerifyScene() {
  return (
    <div className={`${styles.scene} ${styles.verifyScene}`}>
      <div className={styles.sourceCard}>
        <small>Retrieved source</small>
        <p>Changes to the supply chain require considerable time and resources…</p>
        <span>AAPL · 10-K · Item 1A</span>
      </div>
      <div className={styles.verifyBeam} aria-hidden="true">
        <i />
      </div>
      <div className={styles.checkCard}>
        <CheckCircle2 size={28} aria-hidden="true" />
        <strong>Supported</strong>
        <span>source + time match</span>
      </div>
    </div>
  );
}

function ResearchScene() {
  return (
    <div className={`${styles.scene} ${styles.researchScene}`}>
      <div className={styles.outputCard}>
        <span>01</span>
        <strong>Cited answer</strong>
        <i className={styles.outputLine} />
      </div>
      <div className={styles.outputCard}>
        <span>02</span>
        <strong>Parquet panel</strong>
        <div className={styles.miniTable} aria-hidden="true">
          <i />
          <i />
          <i />
        </div>
      </div>
      <div className={styles.outputCard}>
        <span>03</span>
        <strong>Event study</strong>
        <div className={styles.miniBars} aria-hidden="true">
          <i />
          <i />
          <i />
          <i />
        </div>
      </div>
      <div className={styles.lineageTag}>same source lineage</div>
    </div>
  );
}

const SCENES = [FilingScene, ParseScene, RetrieveScene, VerifyScene, ResearchScene] as const;

export function SystemFlow() {
  const reducedMotion = usePrefersReducedMotion();
  const [activeStage, setActiveStage] = useState(0);

  useEffect(() => {
    if (reducedMotion) return;
    const timer = window.setInterval(() => {
      setActiveStage((current) => (current + 1) % STAGES.length);
    }, 1900);
    return () => window.clearInterval(timer);
  }, [reducedMotion]);

  const ActiveScene = SCENES[activeStage];

  return (
    <section className={styles.section} aria-labelledby="system-flow-title">
      <div className={styles.heading}>
        <p className="eyebrow">Under the hood</p>
        <h2 id="system-flow-title">From filing to evidence</h2>
        <p>Watch one source move through the system.</p>
      </div>

      <div className={styles.flow}>
        <div className={styles.stageRail} aria-label="FDRE processing stages">
          {STAGES.map((stage, index) => {
            const Icon = stage.icon;
            return (
              <div className={styles.stageSlot} key={stage.label}>
                <button
                  type="button"
                  className={index === activeStage ? styles.activeStage : undefined}
                  onClick={() => setActiveStage(index)}
                  aria-pressed={index === activeStage}
                >
                  <span className={styles.stageIcon}>
                    <Icon size={18} aria-hidden="true" />
                  </span>
                  <span>
                    <strong>{stage.label}</strong>
                    <small>{stage.detail}</small>
                  </span>
                </button>
                {index < STAGES.length - 1 && <span className={styles.connector} aria-hidden="true"><i /></span>}
              </div>
            );
          })}
        </div>

        <div className={styles.viewport} key={activeStage}>
          <div className={styles.viewportChrome}>
            <span />
            <span />
            <span />
            <small>{STAGES[activeStage].label.toLowerCase()}</small>
          </div>
          <ActiveScene />
        </div>
      </div>

      <div className={styles.actions}>
        <Link href="/">
          Open console <ArrowUpRight size={15} aria-hidden="true" />
        </Link>
        <a
          href="https://github.com/kenchengkc/the-financial-document-retrieval-engine#architecture"
          target="_blank"
          rel="noreferrer"
        >
          Architecture <ArrowUpRight size={15} aria-hidden="true" />
        </a>
      </div>
    </section>
  );
}
