"use client";

import Link from "next/link";
import { useState } from "react";
import { MatchCard } from "@/components/match";
import { useIsOwner, useMe } from "@/components/shell";
import { Badge, Button, Card, CardHeader, Disclaimer, Empty, ErrorNote, Loading, PageHeader, Stat } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { fmtDateTime, humanize } from "@/lib/format";
import type { Dashboard, MatchList } from "@/lib/types";
import { useApi } from "@/lib/use-api";

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export default function DashboardPage() {
  const owner = useIsOwner();
  const me = useMe();
  const dash = useApi<Dashboard>("/api/v1/dashboard");
  const top = useApi<MatchList>("/api/v1/matches?limit=5");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);

  async function rescore() {
    setBusy(true);
    setErr(null);
    try {
      await api.post("/api/v1/matches/run");
      await Promise.all([dash.reload(), top.reload()]);
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  if (dash.loading && !dash.data) return <Loading />;
  if (dash.error) return <ErrorNote error={dash.error} />;
  const d = dash.data!;
  const scanOk = d.jobs.scanned_today >= d.jobs.daily_minimum;
  const elig = d.jobs.by_pk_eligibility;

  return (
    <>
      <PageHeader
        title={`${greeting()}, ${me.display_name.split(" ")[0]}`}
        sub={<Disclaimer text={`${d.label}. ${d.disclaimer}`} />}
        actions={
          owner && (
            <Button onClick={rescore} disabled={busy} title="Re-score all current jobs. No job site is contacted.">
              {busy ? "Re-scoring…" : "Re-score jobs"}
            </Button>
          )
        }
      />
      <ErrorNote error={err} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat
          label={`Matches at or above ${d.threshold}`}
          value={d.matches.qualifying}
          sub={`${d.matches.new} new`}
          tone={d.matches.qualifying ? "good" : "ok"}
          icon="target"
        />
        <Stat label="Below threshold" value={d.matches.below_threshold} sub="eligible, but scored under it" tone="ok" icon="chart" />
        <Stat label="Hidden by knockouts" value={d.matches.hidden} sub="not open to you, too senior, …" tone="muted" icon="eye" />
        <Stat
          label="Postings fetched today"
          value={d.jobs.scanned_today}
          sub={`daily minimum ${d.jobs.daily_minimum}`}
          tone={scanOk ? "good" : "warn"}
          icon="briefcase"
        />
      </div>

      <div className="mt-8 grid gap-6 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-2">
          <div className="flex items-baseline justify-between">
            <h2 className="text-[15px] font-semibold">Top matches</h2>
            <Link href="/matches" className="text-sm text-accent hover:underline">
              All matches →
            </Link>
          </div>
          {top.loading && !top.data ? (
            <Loading />
          ) : top.data && top.data.matches.length > 0 ? (
            top.data.matches.map((m) => <MatchCard key={m.match_id} m={m} threshold={d.threshold} />)
          ) : (
            <Empty title={`No jobs at or above ${d.threshold} right now`}>
              {d.matches.below_threshold > 0 ? (
                <>
                  {d.matches.below_threshold} jobs scored below it.{" "}
                  <Link className="text-accent hover:underline" href="/matches?min=0">
                    See them with their gaps
                  </Link>
                  .
                </>
              ) : (
                "Run a scan to fetch new postings."
              )}
            </Empty>
          )}
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader
              title="Your profile facts"
              sub="Scores assume pending facts are true. Verify them so applications can use them."
            />
            <div className="space-y-2.5 px-5 py-4 text-sm">
              <Row label="Pending review" value={d.facts.pending} tone={d.facts.pending ? "warn" : "good"} />
              <Row label="Verified" value={d.facts.verified} />
              <Row label="Rejected" value={d.facts.rejected} />
              <Row label="With conflicts" value={d.facts.conflicts} tone={d.facts.conflicts ? "bad" : undefined} />
              <Link href="/profile" className="inline-block pt-1 font-medium text-accent hover:underline">
                Review facts →
              </Link>
            </div>
          </Card>

          <Card>
            <CardHeader title="Target jobs" sub={`${d.jobs.targets} in your role families, ${d.jobs.unique} total`} />
            <div className="space-y-2.5 px-5 py-4 text-sm">
              <Row label="Open to Pakistan" value={elig.eligible ?? 0} tone="good" />
              <Row label="Unknown (not stated)" value={elig.unknown ?? 0} tone="warn" />
              <Row label="Not open to Pakistan" value={elig.ineligible ?? 0} />
              {d.metered_sources.map((s) => (
                <Row key={s.source} label={`${humanize(s.source)} quota used`} value={`${s.used} / ${s.quota}`} />
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader
              title="GitHub"
              sub={d.github.username ? `${d.github.username} · ${d.github.repos} repos` : "Not synced yet"}
            />
            <div className="px-5 py-4 text-sm text-muted">Last synced {fmtDateTime(d.github.last_synced_at)}</div>
          </Card>

          <Card>
            <CardHeader title="Recent agent runs" />
            <ul className="divide-y divide-border text-sm">
              {d.recent_runs.map((r, i) => (
                <li key={i} className="flex items-center justify-between gap-2 px-5 py-2.5">
                  <span className="truncate">{humanize(r.agent)}</span>
                  <span className="flex shrink-0 items-center gap-2 text-xs text-muted">
                    {fmtDateTime(r.started_at)}
                    <Badge tone={r.status === "succeeded" ? "good" : r.status === "failed" ? "bad" : "muted"}>
                      {r.errors ? `${r.errors} error${r.errors > 1 ? "s" : ""}` : r.status}
                    </Badge>
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </>
  );
}

function Row({ label, value, tone }: { label: string; value: React.ReactNode; tone?: "good" | "warn" | "bad" }) {
  const cls = tone === "good" ? "text-good" : tone === "warn" ? "text-warn" : tone === "bad" ? "text-bad" : "";
  return (
    <div className="flex justify-between gap-2">
      <span className="text-muted">{label}</span>
      <span className={`tabular font-medium ${cls}`}>{value}</span>
    </div>
  );
}
