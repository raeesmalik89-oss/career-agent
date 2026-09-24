"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Feedback, scoreClass } from "@/components/feedback";
import { Badge, Button, Card, ErrorNote, Loading, PageHeader, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { AnswerFeedback, InterviewSessionDetail, NextQuestion } from "@/lib/types";
import { useApi } from "@/lib/use-api";

export default function SessionPage() {
  const { id } = useParams<{ id: string }>();
  const session = useApi<InterviewSessionDetail>(`/api/v1/interview/sessions/${id}`);
  const [answer, setAnswer] = useState("");
  const [feedback, setFeedback] = useState<AnswerFeedback | null>(null);
  const [current, setCurrent] = useState<NextQuestion | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);

  if (session.loading && !session.data) return <Loading />;
  if (!session.data) return <ErrorNote error={session.error} />;
  const s = session.data;
  const q = current === undefined ? s.next : current;

  async function submit() {
    if (!q) return;
    setBusy(true);
    setErr(null);
    try {
      const fb = await api.post<AnswerFeedback>(`/api/v1/interview/sessions/${s.id}/answer`, { question_id: q.question_id, answer });
      setFeedback(fb);
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  async function next() {
    setCurrent(feedback?.next ?? null);
    setFeedback(null);
    setAnswer("");
    if (!feedback?.next) await session.reload();
  }

  const done = !q && !feedback;
  return (
    <>
      <Link href="/interview" className="text-sm text-muted hover:text-text">
        ← Interview coach
      </Link>
      <PageHeader title={s.mode_title ?? "Mock interview"} sub={`${s.answered} of ${s.total} answered`} />
      <ErrorNote error={err} />

      {q && (
        <Card className="p-5">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
            <span className="tabular">
              Question {q.index} of {q.total}
            </span>
            <Badge>{q.section_title}</Badge>
            <Badge tone={q.difficulty === "hard" ? "bad" : q.difficulty === "medium" ? "warn" : "muted"}>{q.difficulty}</Badge>
          </div>
          <h2 className="mt-3 text-lg font-semibold leading-snug">{q.question}</h2>
          <p className="mt-1 text-sm text-muted">{q.tests}</p>
          {!feedback ? (
            <>
              <textarea
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                rows={8}
                placeholder="Answer as you would say it in the interview…"
                aria-label="Your answer"
                className="mt-4 w-full rounded-md border border-border bg-bg p-3 text-sm"
              />
              <div className="mt-2 flex items-center gap-3">
                <Button variant="primary" disabled={busy || !answer.trim()} onClick={submit}>
                  {busy ? "Checking…" : "Submit answer"}
                </Button>
                <span className="text-xs text-muted tabular">{answer.trim() ? answer.trim().split(/\s+/).length : 0} words · aim for 80-200</span>
              </div>
            </>
          ) : (
            <div className="mt-4 space-y-4">
              <details className="rounded-md border border-border p-3 text-sm">
                <summary className="cursor-pointer text-muted">Your answer</summary>
                <p className="mt-2 whitespace-pre-wrap">{answer}</p>
              </details>
              <Feedback fb={feedback} />
              <Button variant="primary" onClick={next}>
                {feedback.next ? "Next question" : "Finish"}
              </Button>
            </div>
          )}
        </Card>
      )}

      {done && (
        <div className="space-y-4">
          <Card className="p-5">
            <p className="text-sm text-muted">Session complete</p>
            <p className={cx("tabular text-4xl font-semibold", s.avg_score !== null && scoreClass(s.avg_score))}>
              {s.avg_score !== null ? Math.round(s.avg_score) : "—"}
              <span className="text-sm font-normal text-faint">/100 average</span>
            </p>
            <p className="mt-1 text-xs text-muted">{s.disclaimer}</p>
          </Card>
          {s.items.map((it) => (
            <details key={it.question_id} className="rounded-xl border border-border bg-surface p-4 shadow-card">
              <summary className="flex cursor-pointer items-center justify-between gap-3 text-sm font-medium">
                <span>{it.question}</span>
                {it.score !== null && <span className={cx("tabular", scoreClass(it.score))}>{it.score}</span>}
              </summary>
              <div className="mt-3">
                {it.your_answer && <p className="mb-3 whitespace-pre-wrap text-sm text-muted">{it.your_answer}</p>}
                <Feedback fb={it} />
              </div>
            </details>
          ))}
          <Link href="/interview" className="inline-block text-sm text-accent hover:underline">
            Start another session →
          </Link>
        </div>
      )}
    </>
  );
}
