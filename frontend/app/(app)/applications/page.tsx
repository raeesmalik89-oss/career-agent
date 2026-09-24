"use client";

import Link from "next/link";
import { Badge, Empty, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { STATUS_TONE, daysAgo, fmtScore, humanize } from "@/lib/format";
import type { ApplicationSummary } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const GROUPS: { title: string; statuses: string[]; hint: string }[] = [
  { title: "Waiting for your approval", statuses: ["prepared", "pending_approval", "failed"], hint: "Review, fill the gaps, then approve." },
  { title: "Approved: submit these yourself", statuses: ["approved", "awaiting_manual_submit"], hint: "Open the posting, upload the resume, paste the answers, then mark as applied." },
  { title: "In progress", statuses: ["applied", "interview", "technical_interview", "hr_interview", "offer"], hint: "" },
  { title: "Closed", statuses: ["rejected", "withdrawn"], hint: "" },
];

export default function ApplicationsPage() {
  const list = useApi<ApplicationSummary[]>("/api/v1/applications");
  if (list.loading && !list.data) return <Loading />;
  const apps = list.data ?? [];
  return (
    <>
      <PageHeader
        title="Applications"
        sub="Nothing is ever sent without your approval. Packages are built only from your facts; you submit on the employer's site."
      />
      <ErrorNote error={list.error} />
      {!apps.length ? (
        <Empty title="No applications yet">
          Open a job from <Link href="/matches" className="text-accent hover:underline">Matches</Link> and choose “Prepare application”.
        </Empty>
      ) : (
        GROUPS.map((g) => {
          const rows = apps.filter((a) => g.statuses.includes(a.status));
          if (!rows.length) return null;
          return (
            <section key={g.title} className="mb-6">
              <h2 className="text-sm font-semibold">
                {g.title} <span className="text-muted tabular">({rows.length})</span>
              </h2>
              {g.hint && <p className="mb-2 text-xs text-muted">{g.hint}</p>}
              <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface shadow-card">
                {rows.map((a) => (
                  <li key={a.id}>
                    <Link href={`/applications/${a.id}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 hover:bg-surface-2">
                      <span className="min-w-0 flex-1">
                        <span className="font-medium">{a.job.title}</span>
                        <span className="block text-xs text-muted">
                          {a.job.company}
                          {a.job.location ? ` · ${a.job.location}` : ""} · updated {daysAgo(a.last_update)}
                        </span>
                      </span>
                      {a.score !== null && <span className="text-sm text-muted tabular">{fmtScore(a.score)}/100</span>}
                      <Badge tone={STATUS_TONE[a.status] ?? "muted"}>{humanize(a.status)}</Badge>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          );
        })
      )}
    </>
  );
}
