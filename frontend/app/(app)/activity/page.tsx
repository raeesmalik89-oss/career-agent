"use client";

import { useState } from "react";
import { useCanEdit } from "@/components/shell";
import { Badge, Card, Empty, ErrorNote, Loading, PageHeader, cx } from "@/components/ui";
import { fmtDateTime, humanize } from "@/lib/format";
import type { AgentRun, AuditEntry } from "@/lib/types";
import { useApi } from "@/lib/use-api";

export default function ActivityPage() {
  const owner = useCanEdit();
  const [tab, setTab] = useState<"audit" | "runs">("audit");
  const audit = useApi<AuditEntry[]>(owner && tab === "audit" ? "/api/v1/audit-logs?limit=200" : null);
  const runs = useApi<AgentRun[]>(owner && tab === "runs" ? "/api/v1/agent-runs?limit=100" : null);
  const [open, setOpen] = useState<string | null>(null);

  if (!owner) return <Empty title="Only the owner can see the audit log" />;

  return (
    <>
      <PageHeader title="Activity" sub="The audit log is append-only: entries cannot be edited or deleted." />
      <div className="mb-4 inline-flex rounded-md border border-border bg-surface p-0.5" role="tablist">
        {(
          [
            ["audit", "Audit log"],
            ["runs", "Agent runs"],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={cx("rounded px-3 py-1.5 text-sm", tab === k ? "bg-accent-soft font-medium text-accent" : "text-muted")}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "audit" &&
        (audit.loading && !audit.data ? (
          <Loading />
        ) : audit.error ? (
          <ErrorNote error={audit.error} />
        ) : (
          <Card>
            <ul className="divide-y divide-border text-sm">
              {(audit.data ?? []).map((a) => (
                <li key={a.id}>
                  <button
                    className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-left hover:bg-surface-2"
                    onClick={() => setOpen(open === a.id ? null : a.id)}
                    aria-expanded={open === a.id}
                  >
                    <span className="w-32 shrink-0 text-xs text-muted tabular">{fmtDateTime(a.at)}</span>
                    <span className="font-medium">{a.action}</span>
                    <Badge>{a.actor + (a.actor_detail ? ` · ${a.actor_detail}` : "")}</Badge>
                    {a.entity_type && <span className="text-xs text-muted">{a.entity_type}</span>}
                  </button>
                  {open === a.id && (
                    <pre className="overflow-x-auto bg-surface-2 px-4 py-2 text-xs">
                      {JSON.stringify({ before: a.before, after: a.after, reason: a.reason }, null, 2)}
                    </pre>
                  )}
                </li>
              ))}
            </ul>
          </Card>
        ))}

      {tab === "runs" &&
        (runs.loading && !runs.data ? (
          <Loading />
        ) : runs.error ? (
          <ErrorNote error={runs.error} />
        ) : (
          <Card>
            <ul className="divide-y divide-border text-sm">
              {(runs.data ?? []).map((r) => (
                <li key={r.id}>
                  <button
                    className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-left hover:bg-surface-2"
                    onClick={() => setOpen(open === r.id ? null : r.id)}
                    aria-expanded={open === r.id}
                  >
                    <span className="w-32 shrink-0 text-xs text-muted tabular">{fmtDateTime(r.started_at)}</span>
                    <span className="font-medium">{humanize(r.agent_name)}</span>
                    <Badge tone={r.status === "succeeded" ? "good" : r.status === "failed" ? "bad" : "muted"}>{r.status}</Badge>
                    <span className="truncate text-xs text-muted">{r.input_summary}</span>
                  </button>
                  {open === r.id && (
                    <div className="space-y-1 bg-surface-2 px-4 py-2 text-xs">
                      {r.errors.map((e, i) => (
                        <p key={i} className="text-bad">
                          {e.code}: {e.message}
                        </p>
                      ))}
                      <pre className="overflow-x-auto">{JSON.stringify(r.output, null, 2).slice(0, 4000)}</pre>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </Card>
        ))}
    </>
  );
}
