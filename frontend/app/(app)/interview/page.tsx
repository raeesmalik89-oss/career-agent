"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { scoreClass } from "@/components/feedback";
import { useIsOwner } from "@/components/shell";
import { Badge, Button, Card, CardHeader, Empty, ErrorNote, Loading, PageHeader, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { fmtDateTime, humanize } from "@/lib/format";
import type { InterviewPack, InterviewSessionDetail, InterviewStats, PackQuestion } from "@/lib/types";
import { useApi } from "@/lib/use-api";

type Tab = "mock" | "pack" | "progress";
const MODES = [
  { key: "pack", label: "Mixed (all sections)" },
  { key: "target", label: "Skills your target jobs ask for" },
  { key: "gaps", label: "Gap skills" },
  { key: "projects", label: "Your projects and CV" },
  { key: "scenarios", label: "Troubleshooting" },
  { key: "design", label: "System design and SRE" },
  { key: "hr", label: "HR and behavioural" },
];

export default function InterviewPage() {
  const [tab, setTab] = useState<Tab>("mock");
  return (
    <>
      <PageHeader
        title="Interview coach"
        sub="A fresh pack of 60 questions every day, weighted towards what your target jobs ask for, your gaps, your own projects, and anything you answered weakly before."
      />
      <div className="mb-5 inline-flex rounded-md border border-border bg-surface p-0.5" role="tablist">
        {(
          [
            ["mock", "Mock interview"],
            ["pack", "Today's pack"],
            ["progress", "Progress"],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={cx("rounded px-3 py-1.5 text-sm", tab === k ? "bg-accent-soft font-medium text-accent" : "text-muted hover:text-text")}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "mock" && <MockStart />}
      {tab === "pack" && <PackView />}
      {tab === "progress" && <Progress />}
    </>
  );
}

function MockStart() {
  const owner = useIsOwner();
  const router = useRouter();
  const sessions = useApi<{ id: string; mode: string; started_at: string; ended_at: string | null; avg_score: number | null; total: number }[]>(
    "/api/v1/interview/sessions?limit=10",
  );
  const [mode, setMode] = useState("pack");
  const [count, setCount] = useState(10);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);

  async function start() {
    setBusy(true);
    setErr(null);
    try {
      const s = await api.post<InterviewSessionDetail>("/api/v1/interview/sessions", { mode, count });
      router.push(`/interview/${s.id}`);
    } catch (e) {
      setErr(e as ApiError);
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card className="p-4">
        <h2 className="text-sm font-semibold">Start a mock interview</h2>
        <p className="mt-1 text-sm text-muted">
          One question at a time. Answer as you would out loud; the model answer appears only after you answer.
        </p>
        <label className="mt-4 block text-sm font-medium" htmlFor="mode">
          Focus
        </label>
        <select id="mode" value={mode} onChange={(e) => setMode(e.target.value)} className="mt-1 h-9 w-full rounded-md border border-border bg-bg px-2 text-sm">
          {MODES.map((m) => (
            <option key={m.key} value={m.key}>
              {m.label}
            </option>
          ))}
        </select>
        <label className="mt-3 block text-sm font-medium" htmlFor="count">
          Questions
        </label>
        <select id="count" value={count} onChange={(e) => setCount(Number(e.target.value))} className="mt-1 h-9 w-full rounded-md border border-border bg-bg px-2 text-sm">
          {[5, 10, 15, 20].map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
        <ErrorNote error={err} />
        <Button variant="primary" className="mt-4" disabled={!owner || busy} onClick={start}>
          {busy ? "Starting…" : "Start"}
        </Button>
      </Card>
      <Card>
        <CardHeader title="Recent sessions" />
        {sessions.data && sessions.data.length ? (
          <ul className="divide-y divide-border text-sm">
            {sessions.data.map((s) => (
              <li key={s.id}>
                <Link href={`/interview/${s.id}`} className="flex items-center justify-between gap-2 px-4 py-2 hover:bg-surface-2">
                  <span>
                    {MODES.find((m) => m.key === s.mode)?.label ?? humanize(s.mode)}
                    <span className="block text-xs text-muted">
                      {fmtDateTime(s.started_at)} · {s.total} questions {s.ended_at ? "" : "· in progress"}
                    </span>
                  </span>
                  {s.avg_score !== null && <span className={cx("tabular font-semibold", scoreClass(s.avg_score))}>{Math.round(s.avg_score)}</span>}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-4 py-3 text-sm text-muted">No sessions yet.</p>
        )}
      </Card>
    </div>
  );
}

function PackView() {
  const owner = useIsOwner();
  const pack = useApi<InterviewPack>("/api/v1/interview/packs/today");
  const [busy, setBusy] = useState(false);
  if (pack.loading && !pack.data) return <Loading label="Building today's pack…" />;
  if (!pack.data) return <ErrorNote error={pack.error} />;
  const p = pack.data;
  if (!p.total) return <Empty title="No pack for today yet" />;

  async function regenerate() {
    if (!confirm("Build a new pack for today? Today's questions are replaced.")) return;
    setBusy(true);
    try {
      pack.setData(await api.post<InterviewPack>("/api/v1/interview/packs/today/regenerate"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">
          {p.total} questions for {p.date}. Try answering each one before opening the model answer.
        </p>
        {owner && (
          <Button size="sm" disabled={busy} onClick={regenerate}>
            Rebuild today's pack
          </Button>
        )}
      </div>
      {p.sections.map((s) => (
        <section key={s.key}>
          <h2 className="mb-2 text-sm font-semibold">
            {s.title} <span className="text-muted tabular">({s.questions.length})</span>
          </h2>
          <div className="space-y-2">
            {s.questions.map((q, i) => (
              <PackItem key={q.id} q={q} n={i + 1} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function PackItem({ q, n }: { q: PackQuestion; n: number }) {
  const [open, setOpen] = useState(false);
  return (
    <Card className="p-3">
      <button className="flex w-full items-start gap-3 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="tabular text-xs text-faint">{n}.</span>
        <span className="flex-1 text-sm font-medium">{q.question}</span>
        <Badge tone={q.difficulty === "hard" ? "bad" : q.difficulty === "medium" ? "warn" : "muted"}>{q.difficulty}</Badge>
      </button>
      {open && (
        <div className="mt-3 space-y-2 border-t border-border pt-3 text-sm">
          <p className="text-muted">
            <span className="font-medium text-text">Tests: </span>
            {q.tests}
          </p>
          <p>
            <span className="font-medium">Key points: </span>
            {q.key_points.join(" · ")}
          </p>
          <p className="whitespace-pre-wrap rounded-md bg-surface-2 p-2">{q.model_answer}</p>
          {q.spoken_answer && (
            <p>
              <span className="font-medium">Say it simply: </span>
              {q.spoken_answer}
            </p>
          )}
          {q.common_mistakes.length > 0 && (
            <p className="text-muted">
              <span className="font-medium text-text">Avoid: </span>
              {q.common_mistakes.join(" ")}
            </p>
          )}
          <p className="text-muted">
            <span className="font-medium text-text">Follow-up: </span>
            {q.follow_up}
          </p>
        </div>
      )}
    </Card>
  );
}

function Progress() {
  const s = useApi<InterviewStats>("/api/v1/interview/stats");
  if (s.loading && !s.data) return <Loading />;
  if (!s.data) return <ErrorNote error={s.error} />;
  const d = s.data;
  if (!d.answers) return <Empty title="No answers yet">Start a mock interview to see your progress here.</Empty>;
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader title="By section" sub={`${d.answers} answers in ${d.sessions} sessions · average ${d.average}`} />
        <ul className="divide-y divide-border text-sm">
          {Object.entries(d.by_section).map(([k, v]) => (
            <li key={k} className="flex justify-between px-4 py-2">
              <span>
                {v.title} <span className="text-xs text-muted">({v.answers})</span>
              </span>
              <span className={cx("tabular font-semibold", scoreClass(v.average))}>{v.average}</span>
            </li>
          ))}
        </ul>
      </Card>
      <Card>
        <CardHeader title="Practise these again" sub="Your latest answer scored under 70; they come back in the next packs." />
        {d.weakest.length ? (
          <ul className="divide-y divide-border text-sm">
            {d.weakest.map((w) => (
              <li key={w.question} className="flex justify-between gap-3 px-4 py-2">
                <span>{w.question}</span>
                <span className={cx("tabular font-semibold", scoreClass(w.last_score))}>{w.last_score}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-4 py-3 text-sm text-muted">Nothing under 70. Well done.</p>
        )}
      </Card>
      {d.trend.length > 1 && (
        <Card className="lg:col-span-2">
          <CardHeader title="Daily average (last 30 days)" />
          <div className="flex items-end gap-1 px-4 py-4" style={{ height: 140 }}>
            {d.trend.map((t) => (
              <div key={t.day} className="flex flex-1 flex-col items-center gap-1" title={`${t.day}: ${t.average}`}>
                <div className={cx("w-full rounded-t", t.average >= 80 ? "bg-good" : t.average >= 60 ? "bg-warn" : "bg-bad")} style={{ height: `${t.average}%` }} />
              </div>
            ))}
          </div>
        </Card>
      )}
      <p className="text-xs text-muted lg:col-span-2">{d.disclaimer}</p>
    </div>
  );
}
