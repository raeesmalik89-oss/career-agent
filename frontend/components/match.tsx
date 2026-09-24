import Link from "next/link";
import type { Component, Match } from "@/lib/types";
import {
  COMPONENT_LABELS,
  applyUrl,
  KNOCKOUT_LABELS,
  daysAgo,
  fmtSalary,
  fmtScore,
  humanize,
  ratioTone,
  scoreTone,
} from "@/lib/format";
import { Badge, Bar, Button, cx, toneText } from "./ui";

const CONF_TONE = { high: "good", medium: "ok", low: "warn" } as const;

export function ScoreBlock({ score, confidence, threshold, hidden = false, size = "md" }: {
  score: number;
  confidence: "high" | "medium" | "low";
  threshold: number;
  hidden?: boolean;
  size?: "md" | "lg";
}) {
  const tone = scoreTone(score, threshold, hidden);
  const px = size === "lg" ? 88 : 64;
  const r = px / 2 - 5;
  const circ = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score)) / 100;
  return (
    <div className="flex shrink-0 flex-col items-center text-center">
      <div className="relative" style={{ width: px, height: px }} role="img" aria-label={`Fit score ${fmtScore(score)} of 100`}>
        <svg width={px} height={px} viewBox={`0 0 ${px} ${px}`} className="-rotate-90" aria-hidden>
          <circle cx={px / 2} cy={px / 2} r={r} fill="none" strokeWidth={size === "lg" ? 7 : 5.5} className="stroke-surface-3" />
          <circle
            cx={px / 2}
            cy={px / 2}
            r={r}
            fill="none"
            strokeWidth={size === "lg" ? 7 : 5.5}
            strokeLinecap="round"
            strokeDasharray={circ}
            strokeDashoffset={circ * (1 - pct)}
            className={cx("transition-[stroke-dashoffset] duration-700", toneText(tone))}
            stroke="currentColor"
          />
        </svg>
        <div className="absolute inset-0 grid place-items-center">
          <span className={cx("tabular font-semibold leading-none tracking-tight", size === "lg" ? "text-2xl" : "text-lg", toneText(tone))}>
            {fmtScore(score)}
          </span>
        </div>
      </div>
      <div className="mt-1.5 text-[11px] text-muted">
        <span className={toneText(CONF_TONE[confidence])}>{humanize(confidence)}</span> confidence
      </div>
    </div>
  );
}

export function EligibilityBadge({ status, evidence }: { status: string; evidence: string | null }) {
  const tone = status === "eligible" ? "good" : status === "ineligible" ? "bad" : "warn";
  const text = status === "eligible" ? "Open to Pakistan" : status === "ineligible" ? "Not open to Pakistan" : "Pakistan: unknown";
  return (
    <Badge tone={tone} title={evidence ?? "Evidence not found."}>
      {text}
    </Badge>
  );
}

export function Breakdown({ components }: { components: Record<string, Component> }) {
  return (
    <div className="space-y-3">
      {Object.entries(components).map(([key, c]) => (
        <div key={key}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="font-medium">{COMPONENT_LABELS[key] ?? humanize(key)}</span>
            <span className="tabular text-muted">
              {fmtScore(c.points)} / {fmtScore(c.max)}
            </span>
          </div>
          <div className="mt-1">
            <Bar ratio={c.ratio} tone={ratioTone(c.ratio)} />
          </div>
          <p className="mt-1 text-xs text-muted">{c.explanation}</p>
        </div>
      ))}
    </div>
  );
}

export function MatchCard({
  m,
  threshold,
  onDismiss,
}: {
  m: Match;
  threshold: number;
  onDismiss?: (id: string) => void;
}) {
  const hidden = m.knockouts.length > 0;
  const j = m.job;
  const salary = fmtSalary(j.salary);
  return (
    <article className="rounded-xl border border-border bg-surface p-5 shadow-card transition hover:border-border-strong hover:shadow-pop">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            {m.is_new && !hidden && <Badge tone="ok">New</Badge>}
            {hidden && m.knockouts.map((k) => (
              <Badge key={k.code} tone="bad" title={k.reason}>
                Hidden: {KNOCKOUT_LABELS[k.code] ?? k.code}
              </Badge>
            ))}
            <EligibilityBadge status={j.pk_eligibility} evidence={j.pk_eligibility_evidence} />
            <Badge>{humanize(j.remote_type)}</Badge>
            {j.seniority && <Badge>{humanize(j.seniority)}</Badge>}
          </div>
          <h3 className="mt-2 text-base font-semibold leading-snug">
            <Link href={`/jobs/${j.id}`} className="hover:underline">
              {j.title}
            </Link>
          </h3>
          <p className="text-sm text-muted">
            {j.company}
            {j.location ? ` · ${j.location}` : ""} · {daysAgo(j.posted_date ?? j.first_seen_at)}
            {salary ? ` · ${salary}` : ""}
          </p>
        </div>
        <ScoreBlock score={m.estimated_fit_score} confidence={m.confidence} threshold={threshold} hidden={hidden} />
      </div>

      {m.recommendation && <p className="mt-3 text-sm">{m.recommendation}</p>}

      {(m.missing_skills.length > 0 || m.partial_skills.length > 0) && (
        <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
          {m.missing_skills.map((s) => (
            <Badge key={s.skill} tone={s.requirement === "required" ? "bad" : "muted"} title="Evidence not found.">
              missing: {s.name}
            </Badge>
          ))}
          {m.partial_skills.map((s) => (
            <Badge key={s.skill} tone="warn" title={s.reason}>
              partial: {s.name}
            </Badge>
          ))}
        </div>
      )}

      {m.risks.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-muted">
          {m.risks.map((r) => (
            <li key={r} className="flex gap-1.5">
              <span className="text-warn" aria-hidden>
                ▲
              </span>
              {r}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Link
          href={`/jobs/${j.id}`}
          className="inline-flex h-7 items-center rounded-md border border-border px-2.5 text-xs font-medium hover:bg-surface-2"
        >
          Full breakdown
        </Link>
        <a
          href={applyUrl(j)}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="inline-flex h-7 items-center rounded-md px-2.5 text-xs font-medium text-accent hover:bg-accent-soft"
        >
          {j.employer_url ? "Employer's site ↗" : "Open posting ↗"}
        </a>
        {j.aggregator_link && (
          <Badge tone="warn" title="This link goes through a job board, which may ask you to sign up or pay. Open the job to add the employer's own link.">
            job-board link
          </Badge>
        )}
        {onDismiss && !m.dismissed && (
          <Button size="sm" variant="ghost" onClick={() => onDismiss(m.match_id)} className="ml-auto">
            Dismiss
          </Button>
        )}
      </div>
    </article>
  );
}
