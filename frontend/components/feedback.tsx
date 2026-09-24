import type { AnswerFeedback } from "@/lib/types";
import { humanize, ratioTone } from "@/lib/format";
import { Bar, Card, cx, toneText } from "./ui";

export function scoreClass(score: number): string {
  return toneText(score >= 80 ? "good" : score >= 60 ? "warn" : "bad");
}

/** Evaluation of one mock-interview answer: score, rubric, gaps, then the model and spoken answers. */
export function Feedback({ fb }: { fb: AnswerFeedback }) {
  if (fb.score === null) return null;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-3">
        <span className={cx("tabular text-3xl font-semibold", scoreClass(fb.score))}>
          {fb.score}
          <span className="text-sm font-normal text-faint">/100</span>
        </span>
        <span className="text-xs text-muted">{fb.disclaimer}</span>
      </div>

      {fb.rubric && (
        <div className="grid gap-3 sm:grid-cols-2">
          {Object.entries(fb.rubric).map(([k, r]) => (
            <div key={k}>
              <div className="flex justify-between text-sm">
                <span className="font-medium">{humanize(k)}</span>
                <span className="tabular text-muted">
                  {r.points} / {r.max}
                </span>
              </div>
              <div className="mt-1">
                <Bar ratio={r.points / r.max} tone={ratioTone(r.points / r.max)} />
              </div>
              <p className="mt-0.5 text-xs text-muted">{r.note}</p>
            </div>
          ))}
        </div>
      )}

      {(fb.mistakes?.length ?? 0) > 0 && (
        <List title="To fix" items={fb.mistakes!} tone="text-bad" />
      )}
      {(fb.missing_concepts?.length ?? 0) > 0 && (
        <List title="Concepts you did not mention" items={fb.missing_concepts!} tone="text-warn" />
      )}
      {(fb.covered?.length ?? 0) > 0 && <List title="You covered" items={fb.covered!} tone="text-good" />}

      {fb.model_answer && (
        <Card className="bg-surface-2 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Model answer</p>
          <p className="mt-1 whitespace-pre-wrap text-sm">{fb.model_answer}</p>
        </Card>
      )}
      {fb.spoken_version && (
        <Card className="p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Say it simply</p>
          <p className="mt-1 text-sm">{fb.spoken_version}</p>
        </Card>
      )}
      {(fb.common_mistakes?.length ?? 0) > 0 && <List title="Common mistakes" items={fb.common_mistakes!} tone="text-muted" />}
      {fb.follow_up && (
        <p className="text-sm">
          <span className="font-medium">Likely follow-up: </span>
          {fb.follow_up}
        </p>
      )}
    </div>
  );
}

function List({ title, items, tone }: { title: string; items: string[]; tone: string }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</p>
      <ul className="mt-1 space-y-0.5 text-sm">
        {items.map((m) => (
          <li key={m} className="flex gap-2">
            <span className={tone} aria-hidden>
              •
            </span>
            {m}
          </li>
        ))}
      </ul>
    </div>
  );
}
