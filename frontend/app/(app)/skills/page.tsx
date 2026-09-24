"use client";

import Link from "next/link";
import { useState } from "react";
import { useIsOwner } from "@/components/shell";
import { Badge, Bar, Button, Card, CardHeader, Empty, ErrorNote, Loading, PageHeader, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { humanize } from "@/lib/format";
import type { GapReport, LearningPlan, SkillGapRow } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const STATUS_TONE = { have: "good", partial: "warn", missing: "bad" } as const;

export default function SkillsPage() {
  const owner = useIsOwner();
  const [windowDays, setWindowDays] = useState(30);
  const report = useApi<GapReport>(`/api/v1/skills/gaps?window=${windowDays}`);
  const plan = useApi<LearningPlan>("/api/v1/learning");
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function addToPlan(skills?: string[]) {
    setBusy(skills?.[0] ?? "top");
    setErr(null);
    try {
      await api.post("/api/v1/learning/plan", skills ? { skills } : { top: 5 });
      await plan.reload();
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(null);
    }
  }

  const planned = new Set((plan.data?.skills ?? []).map((s) => s.skill));
  const r = report.data;
  const gaps = r?.gaps.filter((g) => g.status !== "have") ?? [];
  const strengths = r?.gaps.filter((g) => g.status === "have") ?? [];

  return (
    <>
      <PageHeader
        title="Skills"
        sub="What the jobs open to you ask for, compared with your evidence. Priority = 40% how often jobs ask for it, 25% how many of your target roles need it, 20% how big your gap is, 15% interview importance."
        actions={
          <div className="inline-flex rounded-md border border-border bg-surface p-0.5" role="tablist" aria-label="Time window">
            {[1, 7, 30].map((w) => (
              <button
                key={w}
                role="tab"
                aria-selected={windowDays === w}
                onClick={() => setWindowDays(w)}
                className={cx("rounded px-3 py-1 text-sm", windowDays === w ? "bg-accent-soft font-medium text-accent" : "text-muted")}
              >
                {w === 1 ? "Today" : `${w} days`}
              </button>
            ))}
          </div>
        }
      />
      <ErrorNote error={err ?? report.error} />

      {plan.data && plan.data.skills.length > 0 && (
        <Card className="mb-6">
          <CardHeader title="Your learning plan" sub="Levels only change with evidence: build the mini-project, push it to GitHub and re-sync." />
          <ul className="divide-y divide-border text-sm">
            {plan.data.skills.map((s) => (
              <li key={s.skill}>
                <Link href={`/skills/${s.skill}`} className="flex flex-wrap items-center gap-3 px-4 py-2.5 hover:bg-surface-2">
                  <span className="w-48 font-medium">{s.name}</span>
                  <span className="w-40">
                    <Bar ratio={s.done / Math.max(s.total, 1)} tone={s.done === s.total ? "good" : "ok"} />
                  </span>
                  <span className="text-xs text-muted tabular">
                    {s.done}/{s.total} done
                  </span>
                  <Badge tone={s.evidence.level === "strong" || s.evidence.level === "working" ? "good" : "warn"}>
                    evidence: {s.evidence.level ?? "none yet"}
                  </Badge>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {report.loading && !r ? (
        <Loading label="Analysing jobs…" />
      ) : r && r.gaps.length ? (
        <div className="grid gap-6 lg:grid-cols-5">
          <div className="lg:col-span-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">
                Gaps to close <span className="text-muted tabular">({gaps.length})</span>
              </h2>
              {owner && gaps.some((g) => g.guide && !planned.has(g.skill)) && (
                <Button size="sm" variant="primary" disabled={busy !== null} onClick={() => addToPlan()}>
                  Plan my top 5
                </Button>
              )}
            </div>
            <p className="mb-3 text-xs text-muted">
              From {r.jobs_analysed} jobs in your target roles that are open to you (last {r.window_days} day{r.window_days > 1 ? "s" : ""}).
            </p>
            <div className="space-y-2">
              {gaps.map((g) => (
                <GapRow key={g.skill} g={g} planned={planned.has(g.skill)} owner={owner} busy={busy === g.skill} onPlan={() => addToPlan([g.skill])} />
              ))}
            </div>
          </div>
          <div className="lg:col-span-2">
            <h2 className="mb-2 text-sm font-semibold">
              Strengths in demand <span className="text-muted tabular">({strengths.length})</span>
            </h2>
            <p className="mb-3 text-xs text-muted">Skills jobs ask for that you already have evidence for. Lead with these.</p>
            <Card>
              <ul className="divide-y divide-border text-sm">
                {strengths.map((g) => (
                  <li key={g.skill} className="flex items-center justify-between gap-2 px-4 py-2">
                    <span>
                      {g.name} <span className="text-xs text-muted">({g.have_level})</span>
                    </span>
                    <span className="text-xs text-muted tabular">{g.jobs_requiring} jobs</span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </div>
      ) : (
        <Empty title="No jobs to analyse yet">Run a scan first.</Empty>
      )}
    </>
  );
}

function GapRow({ g, planned, owner, busy, onPlan }: { g: SkillGapRow; planned: boolean; owner: boolean; busy: boolean; onPlan: () => void }) {
  return (
    <Card className="p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Link href={`/skills/${g.skill}`} className="font-medium hover:underline">
          {g.name}
        </Link>
        <Badge tone={STATUS_TONE[g.status]}>{g.status}</Badge>
        {g.trend_7d !== null && g.trend_7d !== 0 && (
          <span className={cx("text-xs tabular", g.trend_7d > 0 ? "text-warn" : "text-muted")}>
            {g.trend_7d > 0 ? "▲" : "▼"} {Math.abs(g.trend_7d)} pts this week
          </span>
        )}
        <span className="ml-auto text-xs text-muted tabular">priority {g.priority}</span>
      </div>
      <div className="mt-2">
        <Bar ratio={g.priority / 100} tone={g.status === "missing" ? "bad" : "warn"} />
      </div>
      <p className="mt-1.5 text-xs text-muted">
        Asked for in {g.jobs_requiring} jobs ({g.frequency_pct}%)
        {g.families.length ? ` · roles: ${g.families.map(humanize).join(", ")}` : ""} · {g.status_reason}
      </p>
      <div className="mt-2 flex gap-2">
        <Link href={`/skills/${g.skill}`} className="inline-flex h-7 items-center rounded-md border border-border px-2.5 text-xs font-medium hover:bg-surface-2">
          {g.guide ? "Open guide" : "Resources"}
        </Link>
        {owner && g.guide && (
          planned ? (
            <Badge tone="ok">in your plan</Badge>
          ) : (
            <Button size="sm" disabled={busy} onClick={onPlan}>
              Add to plan
            </Button>
          )
        )}
      </div>
    </Card>
  );
}
