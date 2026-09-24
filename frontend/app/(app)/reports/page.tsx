"use client";

import Link from "next/link";
import { useState } from "react";
import { useIsOwner } from "@/components/shell";
import { Button, Card, Empty, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { DailyReportDoc, DailyReportSummary } from "@/lib/types";
import { useApi } from "@/lib/use-api";
import { useRouter } from "next/navigation";

export default function ReportsPage() {
  const owner = useIsOwner();
  const router = useRouter();
  const list = useApi<DailyReportSummary[]>("/api/v1/reports/daily?limit=60");
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function buildNow() {
    setBusy(true);
    try {
      const r = await api.post<DailyReportDoc>("/api/v1/reports/daily");
      router.push(`/reports/${r.date}`);
    } catch (e) {
      setErr(e as ApiError);
      setBusy(false);
    }
  }

  return (
    <>
      <Link href="/automation" className="text-sm text-muted hover:text-text">
        ← Automation
      </Link>
      <PageHeader
        title="Daily reports"
        sub="Built every evening from what actually happened that day: counts only, nothing estimated."
        actions={
          owner && (
            <Button onClick={buildNow} disabled={busy}>
              {busy ? "Building…" : "Build today's report now"}
            </Button>
          )
        }
      />
      <ErrorNote error={err ?? list.error} />
      {list.loading && !list.data ? (
        <Loading />
      ) : list.data && list.data.length ? (
        <Card>
          <ul className="divide-y divide-border text-sm">
            {list.data.map((r) => (
              <li key={r.date}>
                <Link href={`/reports/${r.date}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 hover:bg-surface-2">
                  <span className="w-32 font-medium">{fmtDate(r.date)}</span>
                  <span className="text-muted">{r.headline.new_jobs} new jobs</span>
                  <span className="text-muted">{r.headline.qualifying_new} new matches</span>
                  <span className="text-muted">{r.headline.needs_you} applications waiting</span>
                  <span className="text-muted">{r.headline.answered} answers practised</span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      ) : (
        <Empty title="No reports yet">The evening prep pipeline builds one each day at 20:00.</Empty>
      )}
    </>
  );
}
