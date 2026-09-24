"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { Breakdown, EligibilityBadge, ScoreBlock } from "@/components/match";
import { useIsOwner } from "@/components/shell";
import { Badge, Button, Card, CardHeader, Disclaimer, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { KNOCKOUT_LABELS, applyUrl, daysAgo, employerSearchUrl, fmtSalary, humanize } from "@/lib/format";
import type { ApplicationSummary, JobFull, MatchFull } from "@/lib/types";
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
          <>
            <PrepareButton jobId={job.id} hidden={(m?.knockouts.length ?? 0) > 0} />
            <a
              href={applyUrl(job)}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="inline-flex h-9 items-center rounded-md border border-border bg-surface px-3.5 text-sm font-medium hover:bg-surface-2"
            >
              {job.employer_url ? "Apply on employer's site ↗" : "Open posting ↗"}
            </a>
          </>
        }
      />

      <EmployerLink
        job={job}
        onSaved={async () => {
          await match.reload();
          await jobOnly.reload();
        }}
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

      {job.summary_only && (
        <PasteFullPosting
          job={job}
          onDone={async () => {
            await match.reload();
            await jobOnly.reload();
          }}
        />
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

function PasteFullPosting({ job, onDone }: { job: JobFull; onDone: () => Promise<void> }) {
  const owner = useIsOwner();
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  if (!owner) return null;

  async function save() {
    setBusy(true);
    setErr(null);
    try {
      await api.post("/api/v1/jobs/manual", {
        job_id: job.id,
        title: job.title,
        company: job.company,
        description: text,
        location: job.location ?? undefined,
        remote: ["remote", "hybrid", "onsite"].includes(job.remote_type) ? job.remote_type : undefined,
        url: url.trim() || undefined,
      });
      setText("");
      await onDone();
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mt-6 border-warn/40">
      <CardHeader
        title="Only a summary of this posting is available"
        sub="Requirements such as years of experience cannot be checked from a summary, so this job is not shown as a match. Open the employer's own posting, copy the whole text, and paste it here to score it properly."
      />
      <div className="space-y-2 px-4 py-3">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={8}
          placeholder="Paste the full job description here…"
          aria-label="Full job description"
          className="w-full rounded-md border border-border bg-bg p-2 text-sm"
        />
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="Link to the employer's posting (optional)"
          aria-label="Link to the employer's posting"
          className="h-9 w-full rounded-md border border-border bg-bg px-3 text-sm"
        />
        <ErrorNote error={err} />
        <Button variant="primary" disabled={busy || text.trim().length < 500} onClick={save}>
          {busy ? "Scoring…" : "Use this text and re-score"}
        </Button>
        {text.trim().length > 0 && text.trim().length < 500 && (
          <p className="text-xs text-muted">That looks like a summary too; paste the whole posting.</p>
        )}
      </div>
    </Card>
  );
}

function PrepareButton({ jobId, hidden }: { jobId: string; hidden: boolean }) {
  const owner = useIsOwner();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!owner) return null;

  async function prepare() {
    if (hidden && !confirm("This job is hidden by a knockout rule (see the reasons on this page). Prepare an application anyway?")) return;
    setBusy(true);
    setErr(null);
    try {
      const app = await api.post<{ id: string }>("/api/v1/applications", { job_id: jobId });
      router.push(`/applications/${app.id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const mine = await api.get<ApplicationSummary[]>("/api/v1/applications");
        const found = mine.find((a) => a.job.id === jobId);
        if (found) return router.push(`/applications/${found.id}`);
      }
      setErr(e instanceof ApiError ? e.detail : String(e));
      setBusy(false);
    }
  }

  return (
    <span className="flex items-center gap-2">
      {err && <span className="text-xs text-bad">{err}</span>}
      <Button variant="primary" disabled={busy} onClick={prepare} title="Builds a tailored resume, cover letter and answers from your facts. Nothing is sent.">
        {busy ? "Preparing…" : "Prepare application"}
      </Button>
    </span>
  );
}

function EmployerLink({ job, onSaved }: { job: JobFull; onSaved: () => Promise<void> }) {
  const owner = useIsOwner();
  const [url, setUrl] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  if (!owner) return null;

  async function save(value: string | null) {
    setBusy(true);
    setErr(null);
    try {
      await api.put(`/api/v1/jobs/${job.id}/employer-link`, { url: value });
      setUrl("");
      setEditing(false);
      await onSaved();
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  if (job.employer_url && !editing) {
    return (
      <p className="mb-4 text-sm text-muted">
        Employer link: <a href={job.employer_url} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">{job.employer_url}</a>{" "}
        <button className="text-xs underline" onClick={() => setEditing(true)}>change</button>
      </p>
    );
  }
  if (!job.aggregator_link && !editing) {
    return (
      <p className="mb-4 text-xs text-muted">
        <button className="underline" onClick={() => setEditing(true)}>Add the employer's own link</button>
      </p>
    );
  }
  return (
    <Card className="mb-6 border-warn/40 p-4">
      {job.aggregator_link && (
        <>
          <p className="text-sm font-medium">This posting came through a job board, not the employer.</p>
          <p className="mt-1 text-sm text-muted">
            Job-board links (Jooble, JobLeads and similar) often ask you to sign up or show paid “upgrade your resume” pages.
            You never need them: find the same job on {job.company}&apos;s own careers page and apply there.
          </p>
          <a
            href={employerSearchUrl(job.company, job.title)}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 inline-block text-sm text-accent hover:underline"
          >
            Search for {job.company}&apos;s careers page ↗
          </a>
        </>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://company.com/careers/the-job"
          aria-label="Employer's job link"
          className="h-9 min-w-64 flex-1 rounded-md border border-border bg-bg px-3 text-sm"
        />
        <Button variant="primary" disabled={busy || !url.trim().startsWith("https://")} onClick={() => save(url.trim())}>
          Save employer link
        </Button>
        {job.employer_url && (
          <Button variant="ghost" disabled={busy} onClick={() => save(null)}>
            Remove
          </Button>
        )}
      </div>
      <ErrorNote error={err} />
      {job.summary_only && (
        <p className="mt-2 text-xs text-muted">Tip: also paste the full posting below, so its real requirements are scored.</p>
      )}
    </Card>
  );
}
