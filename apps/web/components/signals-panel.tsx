"use client";

import {
  CircleAlert,
  Fingerprint,
  FlaskConical,
  LoaderCircle,
  ShieldCheck,
  TrendingUp,
} from "lucide-react";
import { useEffect, useState } from "react";

import { fetchSignalStudies } from "@/lib/api";
import type { SignalStudyResponse } from "@/lib/types";

import { ExperimentRegistryPanel } from "./experiment-registry-panel";
import { ExperimentAudit, SignalMonitor } from "./signal-research-views";
import { SignalStudyDetail, signalTabLabel, studyKey } from "./signal-study-detail";

function SignalsModeIntro() {
  return (
    <div className="signals-mode-intro">
      <p className="eyebrow">Filing event studies</p>
      <h2>Signals</h2>
      <p className="panel-lede">
        Filing-based signals evaluated in event studies using only data available on each date.
      </p>
    </div>
  );
}

export function SignalsPanel() {
  const [studies, setStudies] = useState<SignalStudyResponse[]>([]);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [view, setView] = useState<"study" | "monitor" | "audit" | "registry">("study");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    void (async () => {
      const result = await fetchSignalStudies();
      if (active) {
        setStudies(result);
        setActiveKey(result[0] ? studyKey(result[0]) : null);
        setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  if (loading) {
    return (
      <div className="mode-panel">
        <SignalsModeIntro />
        <div className="loading-state" role="status">
          <LoaderCircle className="spin" size={24} />
          <div>
            <h3>Loading published event studies</h3>
            <p>Reading the latest study results…</p>
          </div>
        </div>
      </div>
    );
  }

  if (!studies.length) {
    return (
      <div className="mode-panel">
        <SignalsModeIntro />
        <div className="notice error" role="alert">
          <CircleAlert size={19} />
          <div>
            <strong>No signal study published yet</strong>
            <p>Run `retrieval_pipeline signal-study` to compute and publish one.</p>
          </div>
        </div>
      </div>
    );
  }

  const study = studies.find((candidate) => studyKey(candidate) === activeKey) ?? studies[0];
  return (
    <div className="mode-panel">
      <div className="signals-topline">
        <SignalsModeIntro />
        <div className="signal-view-switch" role="tablist" aria-label="Signal workspace views">
          <button
            type="button"
            role="tab"
            aria-selected={view === "study"}
            className={view === "study" ? "on" : undefined}
            onClick={() => setView("study")}
          >
            <FlaskConical size={14} aria-hidden="true" /> Results
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "monitor"}
            className={view === "monitor" ? "on" : undefined}
            onClick={() => setView("monitor")}
          >
            <TrendingUp size={14} aria-hidden="true" /> Compare
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "audit"}
            className={view === "audit" ? "on" : undefined}
            onClick={() => setView("audit")}
          >
            <ShieldCheck size={14} aria-hidden="true" /> Method
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "registry"}
            className={view === "registry" ? "on" : undefined}
            onClick={() => setView("registry")}
          >
            <Fingerprint size={14} aria-hidden="true" /> Registry
          </button>
        </div>
      </div>
      {view === "monitor" ? (
        <SignalMonitor
          studies={studies}
          onOpenStudy={(candidate) => {
            setActiveKey(studyKey(candidate));
            setView("study");
          }}
        />
      ) : view === "registry" ? (
        <ExperimentRegistryPanel />
      ) : (
        <>
          {studies.length > 1 && (
            <div className="sig-tabs" role="tablist" aria-label="Signal studies">
              {studies.map((candidate) => {
                const key = studyKey(candidate);
                const label = signalTabLabel(candidate);
                const state = candidate.report.quality?.status ?? "Unrated";
                return (
                  <button
                    key={key}
                    type="button"
                    role="tab"
                    aria-selected={key === studyKey(study)}
                    aria-label={`${label}, ${state}`}
                    className={key === studyKey(study) ? "on" : undefined}
                    onClick={() => setActiveKey(key)}
                  >
                    <span className="sig-tab-name">{label}</span>
                  </button>
                );
              })}
            </div>
          )}
          {view === "audit" ? (
            <ExperimentAudit study={study} />
          ) : (
            <SignalStudyDetail study={study} />
          )}
        </>
      )}
    </div>
  );
}
