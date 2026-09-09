"use client";

import {
  CheckCircle2,
  CircleAlert,
  Download,
  Fingerprint,
  LoaderCircle,
  SearchCode,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "/fdre-api").replace(/\/$/, "");

type ExperimentSummary = {
  experiment_id: string;
  signal_name: string;
  outcome_name: string;
  dataset_version: string;
  feature_version: string;
  market_data_version: string;
  universe_snapshot_id: string;
  feature_snapshot_id: string;
  code_sha: string;
  feature_lineage_digest: string | null;
  slice_snapshot_id: string;
  artifact_count: number;
  filing_lineage_count: number;
  final_decisions: Array<Record<string, unknown>>;
  registered_at: string;
};

type ExperimentManifest = {
  experiment_id: string;
  registry_version: string;
  signal_name: string;
  outcome_name: string;
  signal_definition: Record<string, unknown>;
  dataset_version: string;
  feature_version: string;
  market_data_version: string;
  universe_snapshot_id: string;
  feature_snapshot_id: string;
  code_sha: string;
  feature_lineage_digest: string | null;
  fold_schedule: Array<Record<string, unknown>>;
  filing_lineage: Array<Record<string, unknown>>;
  implementation_assumptions: Record<string, unknown>;
  statistical_assumptions: Record<string, unknown>;
  robustness_assumptions: Record<string, unknown>;
  slice_snapshot_id: string;
  artifacts: Array<{
    kind: string;
    experiment_key: string;
    payload_sha256: string;
  }>;
  final_decisions: Array<Record<string, unknown>>;
};

type ReplayResult = {
  experiment_id: string;
  verified: boolean;
  artifact_count: number;
  final_decisions: Array<Record<string, unknown>>;
};

type VerificationState =
  | { state: "idle" }
  | { state: "checking" }
  | { state: "verified"; artifactCount: number }
  | { state: "failed"; reason: string };

type BundleState =
  | { state: "idle" }
  | { state: "downloading" }
  | { state: "failed"; reason: string };

function shortHash(value: string | null, width = 10) {
  if (!value) return "n/a";
  return value.length <= width ? value : `${value.slice(0, width)}…`;
}

function terminalDecision(decisions: Array<Record<string, unknown>>) {
  for (const decision of decisions) {
    for (const key of ["status", "decision", "promotion_status", "action"]) {
      const value = decision[key];
      if (typeof value === "string" && value.length) return value;
    }
  }
  return decisions.length ? "Recorded" : "No decision";
}

function pretty(value: string) {
  return value.replaceAll("_", " ");
}

async function readJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!response.ok) {
    let detail = `request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      // Preserve the status-based fallback.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function saveBundle(experimentId: string, payload: Record<string, unknown>) {
  const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], {
    type: "application/json;charset=utf-8",
  });
  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = `fdre-experiment-${experimentId.slice(0, 12)}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(href), 0);
}

export function ExperimentRegistryPanel() {
  const [experiments, setExperiments] = useState<ExperimentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [manifest, setManifest] = useState<ExperimentManifest | null>(null);
  const [verification, setVerification] = useState<Record<string, VerificationState>>({});
  const [bundles, setBundles] = useState<Record<string, BundleState>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const payload = await readJson<{ experiments: ExperimentSummary[] }>(
          "/research/experiments?limit=25",
        );
        if (!active) return;
        setExperiments(payload.experiments);
        setSelectedId(payload.experiments[0]?.experiment_id ?? null);
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Could not load registry.");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setManifest(null);
      return;
    }
    let active = true;
    void (async () => {
      try {
        const payload = await readJson<ExperimentManifest>(
          `/research/experiments/${encodeURIComponent(selectedId)}`,
        );
        if (active) setManifest(payload);
      } catch (caught) {
        if (active) {
          setManifest(null);
          setError(caught instanceof Error ? caught.message : "Could not inspect manifest.");
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [selectedId]);

  const totals = useMemo(
    () => ({
      artifacts: experiments.reduce((sum, item) => sum + item.artifact_count, 0),
      lineage: experiments.reduce((sum, item) => sum + item.filing_lineage_count, 0),
      verified: Object.values(verification).filter((item) => item.state === "verified").length,
    }),
    [experiments, verification],
  );

  async function verify(experimentId: string) {
    setVerification((current) => ({ ...current, [experimentId]: { state: "checking" } }));
    try {
      const result = await readJson<ReplayResult>(
        `/research/experiments/${encodeURIComponent(experimentId)}/verify`,
      );
      setVerification((current) => ({
        ...current,
        [experimentId]: result.verified
          ? { state: "verified", artifactCount: result.artifact_count }
          : { state: "failed", reason: "Replay did not verify." },
      }));
    } catch (caught) {
      setVerification((current) => ({
        ...current,
        [experimentId]: {
          state: "failed",
          reason: caught instanceof Error ? caught.message : "Verification failed.",
        },
      }));
    }
  }

  async function downloadBundle(experimentId: string) {
    setBundles((current) => ({ ...current, [experimentId]: { state: "downloading" } }));
    try {
      const payload = await readJson<Record<string, unknown>>(
        `/research/experiments/${encodeURIComponent(experimentId)}/bundle`,
      );
      saveBundle(experimentId, payload);
      setBundles((current) => ({ ...current, [experimentId]: { state: "idle" } }));
    } catch (caught) {
      setBundles((current) => ({
        ...current,
        [experimentId]: {
          state: "failed",
          reason: caught instanceof Error ? caught.message : "Bundle export failed.",
        },
      }));
    }
  }

  if (loading) {
    return (
      <div className="loading-state" role="status">
        <LoaderCircle className="spin" size={24} />
        <div>
          <h3>Loading immutable experiment registry</h3>
          <p>Reading persisted research fingerprints and artifact lineage…</p>
        </div>
      </div>
    );
  }

  if (error && experiments.length === 0) {
    return (
      <div className="notice error" role="alert">
        <CircleAlert size={19} />
        <div>
          <strong>Experiment registry unavailable</strong>
          <p>{error}</p>
        </div>
      </div>
    );
  }

  if (experiments.length === 0) {
    return (
      <div className="signal-monitor">
        <div className="signal-view-heading">
          <div>
            <p className="eyebrow">Immutable research roots</p>
            <h3>Experiment registry</h3>
          </div>
          <p>No sealed root manifests have been registered in this environment yet.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="signal-monitor">
      <div className="signal-view-heading">
        <div>
          <p className="eyebrow">Immutable research roots</p>
          <h3>Experiment registry</h3>
        </div>
        <p>
          Content-addressed research roots bind code, point-in-time data, universe identity,
          assumptions, child artifacts, and terminal promotion decisions.
        </p>
      </div>

      <dl className="monitor-stats">
        <div><dt>Registered roots</dt><dd>{experiments.length}</dd></div>
        <div><dt>Child artifacts</dt><dd>{totals.artifacts}</dd></div>
        <div><dt>Filing lineage refs</dt><dd>{totals.lineage.toLocaleString()}</dd></div>
        <div><dt>Verified this session</dt><dd>{totals.verified}</dd></div>
      </dl>

      <div className="monitor-table-wrap">
        <table className="monitor-table">
          <thead>
            <tr>
              <th>Research root</th>
              <th>Signal / outcome</th>
              <th>Code</th>
              <th>Dataset / feature</th>
              <th>Universe</th>
              <th className="num">Artifacts</th>
              <th>Decision</th>
              <th>Integrity</th>
              <th>Bundle</th>
            </tr>
          </thead>
          <tbody>
            {experiments.map((item) => {
              const state = verification[item.experiment_id] ?? { state: "idle" as const };
              const bundle = bundles[item.experiment_id] ?? { state: "idle" as const };
              return (
                <tr key={item.experiment_id}>
                  <td>
                    <button
                      type="button"
                      className="row-action"
                      title="Inspect immutable manifest"
                      onClick={() => setSelectedId(item.experiment_id)}
                    >
                      <Fingerprint size={15} />
                    </button>
                    <strong>{shortHash(item.experiment_id, 12)}</strong>
                    <small>{item.registered_at.slice(0, 10)}</small>
                  </td>
                  <td>
                    <strong>{pretty(item.signal_name)}</strong>
                    <small>{pretty(item.outcome_name)}</small>
                  </td>
                  <td><code>{shortHash(item.code_sha, 8)}</code></td>
                  <td>
                    <strong>{shortHash(item.dataset_version, 16)}</strong>
                    <small>{shortHash(item.feature_version, 16)}</small>
                  </td>
                  <td><code>{shortHash(item.universe_snapshot_id, 10)}</code></td>
                  <td className="num">{item.artifact_count}</td>
                  <td><span className="research-state flat">{terminalDecision(item.final_decisions)}</span></td>
                  <td>
                    {state.state === "verified" ? (
                      <span className="research-state pass"><CheckCircle2 size={12} /> Verified</span>
                    ) : state.state === "failed" ? (
                      <button
                        type="button"
                        className="row-action"
                        title={state.reason}
                        onClick={() => void verify(item.experiment_id)}
                      >
                        <CircleAlert size={15} />
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="row-action"
                        title="Recompute hashes and replay terminal decisions"
                        disabled={state.state === "checking"}
                        onClick={() => void verify(item.experiment_id)}
                      >
                        {state.state === "checking" ? (
                          <LoaderCircle className="spin" size={15} />
                        ) : (
                          <ShieldCheck size={15} />
                        )}
                      </button>
                    )}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="row-action"
                      title={
                        bundle.state === "failed"
                          ? bundle.reason
                          : "Download verified portable bundle"
                      }
                      disabled={bundle.state === "downloading"}
                      onClick={() => void downloadBundle(item.experiment_id)}
                    >
                      {bundle.state === "downloading" ? (
                        <LoaderCircle className="spin" size={15} />
                      ) : bundle.state === "failed" ? (
                        <CircleAlert size={15} />
                      ) : (
                        <Download size={15} />
                      )}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {manifest && (
        <div className="audit-layout">
          <section className="audit-manifest">
            <h4><SearchCode size={15} /> Selected research root</h4>
            <dl>
              <div><dt>Experiment</dt><dd>{shortHash(manifest.experiment_id, 20)}</dd></div>
              <div><dt>Registry</dt><dd>{manifest.registry_version}</dd></div>
              <div><dt>Code SHA</dt><dd>{manifest.code_sha}</dd></div>
              <div><dt>Dataset</dt><dd>{manifest.dataset_version}</dd></div>
              <div><dt>Feature</dt><dd>{manifest.feature_version}</dd></div>
              <div><dt>Market data</dt><dd>{manifest.market_data_version}</dd></div>
              <div><dt>Universe snapshot</dt><dd>{shortHash(manifest.universe_snapshot_id, 20)}</dd></div>
              <div><dt>Feature snapshot</dt><dd>{shortHash(manifest.feature_snapshot_id, 20)}</dd></div>
              <div><dt>Slice snapshot</dt><dd>{shortHash(manifest.slice_snapshot_id, 20)}</dd></div>
              <div><dt>Walk-forward folds</dt><dd>{manifest.fold_schedule.length}</dd></div>
              <div><dt>Filing lineage</dt><dd>{manifest.filing_lineage.length.toLocaleString()}</dd></div>
            </dl>
          </section>

          <section className="audit-gates">
            <h4><ShieldCheck size={15} /> Artifact chain</h4>
            <ul>
              {manifest.artifacts.map((artifact) => (
                <li key={`${artifact.kind}-${artifact.experiment_key}`}>
                  <CheckCircle2 size={16} aria-hidden="true" />
                  <span>
                    <strong>{pretty(artifact.kind)}</strong>
                    <small>{shortHash(artifact.experiment_key, 18)}</small>
                  </span>
                  <em>{shortHash(artifact.payload_sha256, 8)}</em>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}

      <p className="monitor-rule">
        <ShieldCheck size={13} /> Verification recomputes the root identity and child payload hashes,
        then replays the persisted OOS promotion chain. Portable bundle export uses the same
        fail-closed verification before any file is returned; neither path refetches live data.
      </p>
    </div>
  );
}
