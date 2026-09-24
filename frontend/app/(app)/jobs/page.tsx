"use client";

import Link from "next/link";
import { useState } from "react";
import { EligibilityBadge } from "@/components/match";
import { Badge, Empty, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { qs } from "@/lib/api";
import { daysAgo, fmtSalary, humanize } from "@/lib/format";
import type { JobSummary } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const FAMILIES = ["devops", "sre", "aiops", "ai_engineer", "ai_platform", "mlops", "cloud", "platform", "devsecops", "kubernetes", "sre_ai", "cloud_ai_infra"];

export default function JobsPage() {
  const [family, setFamily] = useState("");
  const [pk, setPk] = useState("");
  const [remote, setRemote] = useState("");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const list = useApi<{ total: number; jobs: JobSummary[] }>(
    `/api/v1/jobs${qs({ family, pk, remote, q: query, limit: 300 })}`,
  );

  const select = "h-9 rounded-md border border-border bg-surface px-2 text-sm";
  return (
    <>
      <PageHeader title="All jobs" sub="Every stored posting in your role families, newest first. Scores are on the Matches page." />
      <form
        className="mb-4 flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(q.trim());
        }}
      >
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search title or company"
          aria-label="Search title or company"
          className="h-9 min-w-48 flex-1 rounded-md border border-border bg-surface px-3 text-sm"
        />
        <select className={select} value={family} onChange={(e) => setFamily(e.target.value)} aria-label="Role family">
          <option value="">All families</option>
          {FAMILIES.map((f) => (
            <option key={f} value={f}>
              {humanize(f)}
            </option>
          ))}
        </select>
        <select className={select} value={pk} onChange={(e) => setPk(e.target.value)} aria-label="Pakistan eligibility">
          <option value="">Any eligibility</option>
          <option value="eligible">Open to Pakistan</option>
          <option value="unknown">Unknown</option>
          <option value="ineligible">Not open to Pakistan</option>
        </select>
        <select className={select} value={remote} onChange={(e) => setRemote(e.target.value)} aria-label="Work arrangement">
          <option value="">Any arrangement</option>
          <option value="remote">Remote</option>
          <option value="hybrid">Hybrid</option>
          <option value="onsite">On-site</option>
          <option value="unknown">Not stated</option>
        </select>
      </form>
      <ErrorNote error={list.error} />
      {list.loading && !list.data ? (
        <Loading />
      ) : list.data && list.data.jobs.length ? (
        <div className="overflow-x-auto rounded-xl border border-border bg-surface shadow-card">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted">
              <tr className="border-b border-border">
                <th className="px-4 py-2 font-medium">Job</th>
                <th className="px-2 py-2 font-medium">Where</th>
                <th className="px-2 py-2 font-medium">Pakistan</th>
                <th className="px-2 py-2 font-medium">Level</th>
                <th className="px-4 py-2 font-medium">Seen</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {list.data.jobs.map((j) => (
                <tr key={j.id} className="align-top hover:bg-surface-2">
                  <td className="px-4 py-2">
                    <Link href={`/jobs/${j.id}`} className="font-medium hover:underline">
                      {j.title}
                    </Link>
                    <div className="text-xs text-muted">
                      {j.company}
                      {fmtSalary(j.salary) ? ` · ${fmtSalary(j.salary)}` : ""}
                    </div>
                  </td>
                  <td className="px-2 py-2 text-muted">
                    {humanize(j.remote_type)}
                    {j.location ? <div className="text-xs">{j.location}</div> : null}
                  </td>
                  <td className="px-2 py-2">
                    <EligibilityBadge status={j.pk_eligibility} evidence={j.pk_eligibility_evidence} />
                  </td>
                  <td className="px-2 py-2">
                    {j.seniority ? <Badge>{humanize(j.seniority)}</Badge> : <span className="text-faint">—</span>}
                    {j.experience_required_years !== null && (
                      <div className="text-xs text-muted">{j.experience_required_years}+ yrs</div>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2 text-xs text-muted">{daysAgo(j.last_seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="border-t border-border px-4 py-2 text-xs text-muted tabular">
            Showing {list.data.jobs.length} of {list.data.total}
          </p>
        </div>
      ) : (
        <Empty title="No jobs match these filters" />
      )}
    </>
  );
}
