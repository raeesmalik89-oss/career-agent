"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Breakdown, EligibilityBadge, ScoreBlock } from "@/components/match";
import { Badge, Card, CardHeader, Disclaimer, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { KNOCKOUT_LABELS, daysAgo, fmtSalary, humanize } from "@/lib/format";
import type { JobFull, MatchFull } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const CREDIT_TONE = (c: number) => (c >= 0.8 ? "good" : c >= 0.5 ? "warn" : "bad") as "good" | "warn" | "bad";

export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const match = useApi<MatchFull>(`/api/v1/jobs/${id}/match`);
  const jobOnly = useApi<JobFull>(match.error?.status === 404 ? `/api/v1/jobs/${id}` : null);
  const [fullText, setFullText] = useState(false);

  if (match.loading && !match.data) return <Loading />;
  const m = match.data;
  const job = m?.job ?? jobOnly.data;
  if (!job) return <ErrorNote error={jobOnly.error ?? match.error} />;

  const salary = fmtSalary(job.salary);
  const evidence = m ? Object.entries(m.evidence).sort((a, b) => (a[1].requirement === b[1].requirement ? b[1].credit - a[1].credit : a[1].requirement === "required" ? -1 : 1)) : [];

  return (
    <>
      <Link href="/matches" className="text-sm text-muted hover:text-text">
        ← Matches
      </Link>
      <PageHeader
        title={job.title}
        sub={
          <>
            {job.company}
            {job.location ? ` · ${job.location}` : ""} · {humanize(job.remote_type)} · posted{" "}
            {daysAgo(job.posted_date ?? job.first_seen_at)}
          </>
        }
        actions={
          <a
            href={job.application_url ?? job.url}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="inline-flex h-9 items-center rounded-md border border-border bg-surface px-3.5 text-sm font-medium hover:bg-surface-2"
          >
            Open posting ↗
          </a>
        }
      />

      {m ? (
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="space-y-6 lg:col-span-2">
            <Card className="p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-sm font-medium">{m.label}</p>
                  <Disclaimer text={m.disclaimer} />
                  {m.recommendation && <p className="mt-3 text-sm">{m.recommendation}</p>}
                  {m.previous_score !== null && m.previous_score !== m.estimated_fit_score && (
                    <p className="mt-1 text-xs text-muted">Previously {m.previous_score} (profile or settings changed).</p>
                  )}
                  {m.knockouts.length > 0 && (
                    <ul className="mt-3 space-y-1.5">
                      {m.knockouts.map((k) => (
                        <li key={k.code} className="text-sm">
                          <Badge tone="bad">{KNOCKOUT_LABELS[k.code] ?? k.code}</Badge>{" "}
                          <span className="text-muted">{k.reason}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <ScoreBlock
                  score={m.estimated_fit_score}
                  confidence={m.confidence}
                  threshold={m.threshold}
                  hidden={m.knockouts.length > 0}
                  size="lg"
                />
              </div>
            </Card>

            <Card>
              <CardHeader title="Score breakdown" sub={`Weights from Settings version ${m.settings_version}`} />
              <div className="px-4 py-4">
                <Breakdown components={m.components} />
              </div>
            </Card>

            <Card>
              <CardHeader
                title="Skill evidence"
                sub="1.0 = resume use + GitHub · 0.8 = resume use · 0.7 = GitHub only · 0.5 = listed, medium or adjacent · 0 = Evidence not found."
              />
              {evidence.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-left text-xs text-muted">
                      <tr className="border-b border-border">
                        <th className="px-4 py-2 font-medium">Skill</th>
                        <th className="px-2 py-2 font-medium">Posting</th>
                        <th className="px-2 py-2 font-medium">Credit</th>
                        <th className="px-4 py-2 font-medium">Your evidence</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {evidence.map(([key, e]) => (
                        <tr key={key} className="align-top">
                          <td className="px-4 py-2 font-medium">{e.name}</td>
                          <td className="px-2 py-2 text-muted">{e.requirement}</td>
                          <td className="px-2 py-2">
                            <Badge tone={CREDIT_TONE(e.credit)}>{e.credit.toFixed(1)}</Badge>
                          </td>
                          <td className="px-4 py-2 text-muted">
                            {e.basis}
                            {e.github.length > 0 && (
                              <div className="mt-1 flex flex-wrap gap-x-2 text-xs">
                                {e.github.slice(0, 6).map((g) => (
                                  <a key={g.repo} href={g.url} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                                    {g.repo}
                                  </a>
                                ))}
                                {e.github.length > 6 && <span>+{e.github.length - 6} more</span>}
                              </div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="px-4 py-3 text-sm text-muted">The posting lists no recognisable skills. Evidence not found.</p>
              )}
            </Card>
          </div>

          <div className="space-y-4">
            <ListCard title="Why it matches" items={m.why_matched} tone="good" />
            <ListCard title="What holds it back" items={m.why_not_matched} tone="bad" />
            <ListCard title="Risks" items={m.risks} tone="warn" />
            <JobFacts job={job} salary={salary} />
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-muted">
            Not scored: this job is outside your target role families, or has not been matched yet.
          </p>
          <JobFacts job={job} salary={salary} />
        </div>
      )}

      <Card className="mt-6">
        <CardHeader
          title="Posting text"
          sub="Untrusted text from the job source, shown as plain text."
          action={
            <button className="text-xs text-accent hover:underline" onClick={() => setFullText(!fullText)}>
              {fullText ? "Collapse" : "Show all"}
            </button>
          }
        />
        <div className={`whitespace-pre-wrap px-4 py-3 text-sm ${fullText ? "" : "max-h-72 overflow-hidden"}`}>{job.description}</div>
      </Card>
    </>
  );
}

function ListCard({ title, items, tone }: { title: string; items: string[]; tone: "good" | "bad" | "warn" }) {
  if (!items.length) return null;
  const dot = tone === "good" ? "text-good" : tone === "bad" ? "text-bad" : "text-warn";
  return (
    <Card>
      <CardHeader title={title} />
      <ul className="space-y-2 px-4 py-3 text-sm">
        {items.map((t) => (
          <li key={t} className="flex gap-2">
            <span className={dot} aria-hidden>
              •
            </span>
            <span>{t}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function JobFacts({ job, salary }: { job: JobFull; salary: string | null }) {
  const rows: [string, React.ReactNode][] = [
    ["Pakistan", <EligibilityBadge key="e" status={job.pk_eligibility} evidence={job.pk_eligibility_evidence} />],
    ["Evidence", job.pk_eligibility_evidence ?? "Evidence not found."],
    ["Role family", job.role_family ? humanize(job.role_family) : "—"],
    ["Seniority", job.seniority ? humanize(job.seniority) : "not stated"],
    ["Experience", job.experience_required_years !== null ? `${job.experience_required_years}+ years` : "not stated"],
    ["Salary", salary ? `${salary} (“${job.salary?.source_text ?? "from source"}”)` : "not stated by the source"],
    ["Education", job.education_required ?? "not stated"],
    ["Visa", job.visa_requirement ?? "not stated"],
    ["Sources", job.sources.map(([k]) => k).join(", ")],
  ];
  return (
    <Card>
      <CardHeader title="Posting facts" sub={`Version ${job.content_version}`} />
      <dl className="divide-y divide-border text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="grid grid-cols-3 gap-2 px-4 py-2">
            <dt className="text-muted">{k}</dt>
            <dd className="col-span-2 break-words">{v}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}
