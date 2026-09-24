"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useCanEdit, useIsAdmin } from "@/components/shell";
import { SystemHealthCard } from "@/components/system-health";
import { Badge, Button, Card, CardHeader, ErrorNote, Loading, PageHeader, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { RUN_TONE, fmtDateTime, humanize, relTime } from "@/lib/format";
import type { PipelineRunRow, PipelinesInfo } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const TRIGGER_LABEL = { schedule: "on schedule", catch_up: "caught up late", manual: "run by you" } as const;

export default function AutomationPage() {
  const owner = useCanEdit();
  const admin = useIsAdmin();
  const info = useApi<PipelinesInfo>("/api/v1/pipelines");
  const runs = useApi<PipelineRunRow[]>("/api/v1/pipeline-runs?limit=40");
  const [err, setErr] = useState<ApiError | null>(null);
  const [starting, setStarting] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const anyRunning = (runs.data ?? []).some((r) => r.status === "running");

  // While something runs, refresh every 5 s so the result shows up without reloading.
  const { reload: reloadRuns } = runs;
  const { reload: reloadInfo } = info;
  useEffect(() => {
    if (!anyRunning) return;
    const t = setInterval(() => {
      void reloadRuns();
      void reloadInfo();
    }, 5000);
    return () => clearInterval(t);
  }, [anyRunning, reloadRuns, reloadInfo]);

  async function runNow(name: string) {
    setStarting(name);
    setErr(null);
    try {
      await api.post(`/api/v1/pipelines/${name}/run`);
      await Promise.all([runs.reload(), info.reload()]);
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setStarting(null);
    }
  }

  if (info.loading && !info.data) return <Loading />;
  if (!info.data) return <ErrorNote error={info.error} />;
  const d = info.data;

  return (
    <>
      <PageHeader
        title="Automation"
        sub={`Pipelines run by the scheduler (times in ${d.timezone}). Nothing here ever submits an application: at most it prepares a package for your review.`}
        actions={
          <Link href="/reports" className="inline-flex h-8 items-center rounded-md border border-border px-3 text-sm font-medium hover:bg-surface-2">
            Daily reports
          </Link>
        }
      />
      <ErrorNote error={err} />
      {admin && <SystemHealthCard />}

      <Card className="mb-6">
        <div className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
          <span className={cx("h-2.5 w-2.5 rounded-full", d.scheduler.running ? "bg-good" : "bg-bad")} aria-hidden />
          {d.scheduler.running ? (
            <span>
              Scheduler is running <span className="text-muted">(last check {relTime(d.scheduler.last_seen)})</span>
            </span>
          ) : (
            <span>
              <span className="font-medium">Scheduler is not running.</span>{" "}
              <span className="text-muted">
                {d.scheduler.last_seen ? `Last seen ${relTime(d.scheduler.last_seen)}. ` : ""}
                Start it with start-career-agent.cmd (it opens a &quot;Career Agent Scheduler&quot; window). Missed runs from the last
                few hours are caught up when it starts.
              </span>
            </span>
          )}
          {!d.enabled && <Badge tone="warn">schedules turned off in Settings</Badge>}
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        {d.pipelines.map((p) => (
          <Card key={p.name}>
            <CardHeader
              title={p.title}
              sub={p.about}
              action={
                owner && (
                  <Button size="sm" disabled={anyRunning || starting !== null} onClick={() => runNow(p.name)}>
                    {starting === p.name ? "Starting…" : "Run now"}
                  </Button>
                )
              }
            />
            <dl className="grid grid-cols-[7rem_1fr] gap-y-1 px-4 py-3 text-sm">
              <dt className="text-muted">Schedule</dt>
              <dd>{p.schedule}</dd>
              <dt className="text-muted">Next run</dt>
              <dd>{p.next_run ? `${fmtDateTime(p.next_run)} (${relTime(p.next_run)})` : "—"}</dd>
              <dt className="text-muted">Last run</dt>
              <dd className="flex flex-wrap items-center gap-2">
                {p.last_run ? (
                  <>
                    <Badge tone={RUN_TONE[p.last_run.status]}>{p.last_run.status}</Badge>
                    <span className="text-muted">{relTime(p.last_run.started_at)}</span>
                  </>
                ) : (
                  "never"
                )}
              </dd>
              <dt className="text-muted">Steps</dt>
              <dd className="text-muted">{p.steps.map(humanize).join(" → ")}</dd>
            </dl>
          </Card>
        ))}
      </div>

      <h2 className="mb-2 mt-8 text-sm font-semibold">Recent runs</h2>
      {runs.data && runs.data.length ? (
        <Card>
          <ul className="divide-y divide-border text-sm">
            {runs.data.map((r) => (
              <li key={r.id}>
                <button
                  className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-left hover:bg-surface-2"
                  onClick={() => setOpen(open === r.id ? null : r.id)}
                  aria-expanded={open === r.id}
                >
                  <span className="w-28 shrink-0 text-xs text-muted tabular">{fmtDateTime(r.started_at)}</span>
                  <span className="font-medium">{r.title}</span>
                  <Badge tone={RUN_TONE[r.status]}>{r.status}</Badge>
                  <span className="text-xs text-muted">{TRIGGER_LABEL[r.trigger]}</span>
                </button>
                {open === r.id && (
                  <ol className="space-y-1.5 border-t border-border bg-surface-2 px-4 py-3 text-xs">
                    {r.steps.length === 0 && <li className="text-muted">Still starting…</li>}
                    {r.steps.map((s) => (
                      <li key={s.step} className="flex flex-wrap items-start gap-2">
                        <Badge tone={RUN_TONE[s.status]}>{s.status}</Badge>
                        <span className="font-medium">{humanize(s.step)}</span>
                        {s.seconds !== undefined && <span className="text-faint tabular">{s.seconds}s</span>}
                        <span className="basis-full pl-1 text-muted">
                          {s.error ?? s.note ?? (s.summary ? summarize(s.summary) : "")}
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
              </li>
            ))}
          </ul>
        </Card>
      ) : (
        <p className="text-sm text-muted">No runs yet.</p>
      )}
    </>
  );
}

function summarize(s: Record<string, unknown>): string {
  return Object.entries(s)
    .filter(([, v]) => v !== null && v !== undefined && !(typeof v === "object" && Object.keys(v as object).length === 0))
    .map(([k, v]) => `${humanize(k)}: ${typeof v === "object" ? (Array.isArray(v) ? v.join(", ") : Object.entries(v as object).map(([a, b]) => `${a} ${b}`).join(", ")) : String(v)}`)
    .join(" · ");
}
