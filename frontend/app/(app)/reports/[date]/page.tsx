"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { SimpleMarkdown } from "@/components/markdown";
import { Card, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { fmtDate, fmtDateTime } from "@/lib/format";
import type { DailyReportDoc } from "@/lib/types";
import { useApi } from "@/lib/use-api";

interface TopJob {
  job_id: string;
  title: string;
  company: string;
  score: number;
}

export default function ReportPage() {
  const { date } = useParams<{ date: string }>();
  const res = useApi<DailyReportDoc>(`/api/v1/reports/daily/${date}`);

  if (res.loading && !res.data) return <Loading />;
  if (!res.data) return <ErrorNote error={res.error} />;
  const r = res.data;
  const top = ((r.metrics.jobs as { top_open?: TopJob[] } | undefined)?.top_open ?? []) as TopJob[];

  return (
    <>
      <Link href="/reports" className="text-sm text-muted hover:text-text">
        ← Daily reports
      </Link>
      <PageHeader title={`Report for ${fmtDate(r.date)}`} sub={`Generated ${fmtDateTime(r.generated_at)}.`} />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="px-5 py-4 lg:col-span-2">
          <SimpleMarkdown text={r.content_md.replace(/^# .*\n/, "")} />
        </Card>
        {top.length > 0 && (
          <Card className="self-start">
            <div className="border-b border-border px-4 py-2.5 text-sm font-semibold">Open these jobs</div>
            <ul className="divide-y divide-border text-sm">
              {top.map((j) => (
                <li key={j.job_id}>
                  <Link href={`/jobs/${j.job_id}`} className="flex items-center justify-between gap-2 px-4 py-2 hover:bg-surface-2">
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{j.title}</span>
                      <span className="block truncate text-xs text-muted">{j.company}</span>
                    </span>
                    <span className="tabular text-sm">{j.score}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </>
  );
}
