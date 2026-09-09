"use client";

import {
  CircleAlert,
  GitCompareArrows,
  LoaderCircle,
  Minus,
  Plus,
  ShieldCheck,
} from "lucide-react";
import { FormEvent, useState } from "react";

import {
  fetchUniverseDiff,
  type UniverseConstituent,
  type UniverseConstituentChange,
  type UniverseDiff,
} from "@/lib/universe";

import styles from "./universe-audit.module.css";

const MAX_ROWS = 8;

function shortHash(value: string) {
  return `${value.slice(0, 12)}…`;
}

function readableField(field: string) {
  return field.replaceAll("_", " ");
}

function ConstituentRow({ item }: { item: UniverseConstituent }) {
  return (
    <div className={styles.row}>
      <div className={styles.rowTop}>
        <span className={styles.symbol}>{item.symbol}</span>
        <span className={styles.securityId}>security {item.security_id}</span>
      </div>
      <span className={styles.name}>{item.name ?? item.cik}</span>
      <span className={styles.meta}>
        {item.exchange ?? "exchange unavailable"} · member since {item.membership_effective_from}
      </span>
    </div>
  );
}

function ChangedRow({ item }: { item: UniverseConstituentChange }) {
  const symbolChanged = item.before.symbol !== item.after.symbol;
  return (
    <div className={styles.row}>
      <div className={styles.rowTop}>
        <span className={styles.symbol}>
          {symbolChanged ? `${item.before.symbol} → ${item.after.symbol}` : item.after.symbol}
        </span>
        <span className={styles.securityId}>security {item.security_id}</span>
      </div>
      <span className={styles.name}>{item.after.name ?? item.before.name ?? item.after.cik}</span>
      <span className={styles.fields}>{item.changed_fields.map(readableField).join(" · ")}</span>
    </div>
  );
}

function Group({
  title,
  count,
  icon,
  rows,
}: {
  title: string;
  count: number;
  icon: React.ReactNode;
  rows: React.ReactNode[];
}) {
  const shown = rows.slice(0, MAX_ROWS);
  return (
    <section className={styles.group}>
      <div className={styles.groupHeader}>
        <strong>
          {icon}
          {title}
        </strong>
        <code>{count}</code>
      </div>
      {shown.length ? <div className={styles.rows}>{shown}</div> : <div className={styles.empty}>None</div>}
      {count > MAX_ROWS ? (
        <div className={styles.more}>{count - MAX_ROWS} more in this snapshot comparison</div>
      ) : null}
    </section>
  );
}

export function UniverseAudit() {
  const [fromAsOf, setFromAsOf] = useState("");
  const [toAsOf, setToAsOf] = useState("");
  const [result, setResult] = useState<UniverseDiff | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!fromAsOf || !toAsOf || loading) return;
    if (toAsOf < fromAsOf) {
      setError("The ending snapshot date must be on or after the starting date.");
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await fetchUniverseDiff(fromAsOf, toAsOf));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The universe comparison failed.");
    } finally {
      setLoading(false);
    }
  }

  const summary = result?.summary;
  const summaryCells = result
    ? [
        ["From", summary?.from_count ?? 0],
        ["To", summary?.to_count ?? 0],
        ["Added", summary?.added_count ?? 0],
        ["Removed", summary?.removed_count ?? 0],
        ["Identity / provenance", summary?.changed_count ?? 0],
      ]
    : [];

  return (
    <section className={styles.panel} aria-label="Point-in-time universe audit">
      <div className={styles.header}>
        <div>
          <h3 className={styles.title}>
            <GitCompareArrows size={16} aria-hidden="true" /> Point-in-time universe audit
          </h3>
          <p className={styles.description}>
            Compare two S&amp;P 500 snapshots by stable security identity. Membership additions and
            removals are separated from ticker, name, exchange, effective-date, and source-provenance
            changes.
          </p>
        </div>
        <span className={styles.badge}>
          <ShieldCheck size={13} aria-hidden="true" /> Verified evidence only
        </span>
      </div>

      <form className={styles.form} onSubmit={submit}>
        <label className={styles.field}>
          <span>From snapshot</span>
          <input
            type="date"
            value={fromAsOf}
            max={toAsOf || undefined}
            onChange={(event) => setFromAsOf(event.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span>To snapshot</span>
          <input
            type="date"
            value={toAsOf}
            min={fromAsOf || undefined}
            onChange={(event) => setToAsOf(event.target.value)}
          />
        </label>
        <button
          className={styles.runButton}
          type="submit"
          disabled={!fromAsOf || !toAsOf || loading}
        >
          {loading ? <LoaderCircle className="spin" size={15} /> : <GitCompareArrows size={15} />}
          {loading ? "Comparing" : "Compare snapshots"}
        </button>
      </form>

      {error ? (
        <div className={styles.error} role="alert">
          <CircleAlert size={16} aria-hidden="true" />
          <span>{error}</span>
        </div>
      ) : null}

      {result ? (
        <div className={styles.result}>
          <div className={styles.summary}>
            {summaryCells.map(([label, value]) => (
              <div className={styles.summaryCell} key={String(label)}>
                <strong>{value}</strong>
                <span>{label}</span>
              </div>
            ))}
          </div>

          <p className={styles.snapshots}>
            <span>
              {result.from_as_of} <code title={result.from_snapshot_id}>{shortHash(result.from_snapshot_id)}</code>
            </span>
            <span>
              {result.to_as_of} <code title={result.to_snapshot_id}>{shortHash(result.to_snapshot_id)}</code>
            </span>
          </p>

          <div className={styles.groups}>
            <Group
              title="Added securities"
              count={result.added.length}
              icon={<Plus size={13} aria-hidden="true" />}
              rows={result.added.map((item) => (
                <ConstituentRow key={item.security_id} item={item} />
              ))}
            />
            <Group
              title="Removed securities"
              count={result.removed.length}
              icon={<Minus size={13} aria-hidden="true" />}
              rows={result.removed.map((item) => (
                <ConstituentRow key={item.security_id} item={item} />
              ))}
            />
            <Group
              title="Identity / provenance changes"
              count={result.changed.length}
              icon={<GitCompareArrows size={13} aria-hidden="true" />}
              rows={result.changed.map((item) => (
                <ChangedRow key={item.security_id} item={item} />
              ))}
            />
          </div>
        </div>
      ) : null}
    </section>
  );
}
