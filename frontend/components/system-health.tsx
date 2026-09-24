"use client";

import { useState } from "react";
import { Badge, Button, Card, CardHeader, ErrorNote } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { fmtDateTime, relTime } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface SystemHealth {
  status: "ok" | "warn" | "fail";
  problems: { level: "warn" | "fail"; code: string; message: string }[];
  database: { latency_ms: number; dialect: string; migration: { current: string | null; head: string | null } };
  scheduler: { running: boolean; last_seen: string | null };
  jobs: { last_fetch: string | null };
  backup: { applies: boolean; latest: string | null; size_bytes: number | null; kept: number };
  jooble_quota: { used: number; total: number } | null;
  disk_free_bytes: number;
}

const STATUS = { ok: ["good", "All good"], warn: ["warn", "Needs attention"], fail: ["bad", "Problem"] } as const;

export function SystemHealthCard() {
  const res = useApi<SystemHealth>("/api/v1/system/health");
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function backupNow() {
    setBusy(true);
    setErr(null);
    try {
      await api.post("/api/v1/system/backup");
      await res.reload();
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  const h = res.data;
  if (!h) return res.error ? <ErrorNote error={res.error} /> : null;
  const [tone, label] = STATUS[h.status];
  const gb = (n: number) => `${(n / 1024 ** 3).toFixed(1)} GB`;

  return (
    <Card className="mb-6">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            System health <Badge tone={tone}>{label}</Badge>
          </span>
        }
        action={
          h.backup.applies && (
            <Button size="sm" onClick={backupNow} disabled={busy}>
              {busy ? "Backing up…" : "Back up now"}
            </Button>
          )
        }
      />
      {h.problems.length > 0 && (
        <ul className="space-y-1 border-b border-border px-4 py-3 text-sm">
          {h.problems.map((p) => (
            <li key={p.code} className={p.level === "fail" ? "text-bad" : "text-warn"}>
              {p.level === "fail" ? "✕" : "!"} {p.message}
            </li>
          ))}
        </ul>
      )}
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 px-4 py-3 text-sm md:grid-cols-4">
        <Item label="Database">
          {h.database.dialect}, {h.database.latency_ms} ms, schema {h.database.migration.current ?? "none"}
        </Item>
        <Item label="Last job fetch">{h.jobs.last_fetch ? relTime(h.jobs.last_fetch) : "never"}</Item>
        <Item label="Last backup">
          {!h.backup.applies ? "pg_dump (external)" : h.backup.latest ? `${fmtDateTime(h.backup.latest)} (${h.backup.kept} kept)` : "none yet"}
        </Item>
        <Item label="Free disk">{gb(h.disk_free_bytes)}</Item>
        {h.jooble_quota && (
          <Item label="Jooble requests">
            {h.jooble_quota.total - h.jooble_quota.used} of {h.jooble_quota.total} left
          </Item>
        )}
      </dl>
      <div className="px-4 pb-3">
        <ErrorNote error={err} />
      </div>
    </Card>
  );
}

function Item({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
