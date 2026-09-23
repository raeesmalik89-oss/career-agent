"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { MatchCard } from "@/components/match";
import { useIsOwner } from "@/components/shell";
import { Button, Disclaimer, Empty, ErrorNote, Loading, PageHeader, cx } from "@/components/ui";
import { ApiError, api, qs } from "@/lib/api";
import type { MatchList } from "@/lib/types";
import { useApi } from "@/lib/use-api";

type View = "shown" | "scored" | "all";

const VIEWS: { key: View; label: string; hint: string }[] = [
  { key: "shown", label: "At or above threshold", hint: "The jobs you would be shown" },
  { key: "scored", label: "All eligible", hint: "Every job without a knockout, any score" },
  { key: "all", label: "Including hidden", hint: "Also jobs hidden by knockouts, with the reason" },
];

function MatchesView() {
  const owner = useIsOwner();
  const router = useRouter();
  const params = useSearchParams();
  const view: View = params.get("min") === "0" ? (params.get("hidden") ? "all" : "scored") : "shown";
  const newOnly = params.get("new") === "1";
  const path = `/api/v1/matches${qs({
    min_score: view === "shown" ? undefined : 0,
    include_hidden: view === "all" || undefined,
    new_only: newOnly || undefined,
    limit: 200,
  })}`;
  const list = useApi<MatchList>(path);
  const [err, setErr] = useState<ApiError | null>(null);

  function go(v: View, n = newOnly) {
    router.replace(`/matches${qs({ min: v === "shown" ? undefined : 0, hidden: v === "all" ? 1 : undefined, new: n ? 1 : undefined })}`);
  }

  async function dismiss(id: string) {
    try {
      await api.post(`/api/v1/matches/${id}/dismiss`);
      if (list.data) list.setData({ ...list.data, total: list.data.total - 1, matches: list.data.matches.filter((m) => m.match_id !== id) });
    } catch (e) {
      setErr(e as ApiError);
    }
  }

  async function markSeen() {
    const ids = (list.data?.matches ?? []).filter((m) => m.is_new).map((m) => m.match_id);
    if (!ids.length) return;
    try {
      await api.post("/api/v1/matches/seen", { match_ids: ids });
      await list.reload();
    } catch (e) {
      setErr(e as ApiError);
    }
  }

  const newCount = list.data?.matches.filter((m) => m.is_new && !m.knockouts.length).length ?? 0;

  return (
    <>
      <PageHeader
        title="Matches"
        sub={list.data && <Disclaimer text={`${list.data.label}. ${list.data.disclaimer}`} />}
        actions={
          owner &&
          newCount > 0 && (
            <Button onClick={markSeen} title="They will not be flagged as new again unless the posting changes">
              Mark {newCount} as seen
            </Button>
          )
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-md border border-border bg-surface p-0.5" role="tablist">
          {VIEWS.map((v) => (
            <button
              key={v.key}
              role="tab"
              aria-selected={view === v.key}
              title={v.hint}
              onClick={() => go(v.key)}
              className={cx(
                "rounded px-3 py-1.5 text-sm",
                view === v.key ? "bg-accent-soft font-medium text-accent" : "text-muted hover:text-text",
              )}
            >
              {v.label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1.5 text-sm text-muted">
          <input type="checkbox" checked={newOnly} onChange={(e) => go(view, e.target.checked)} />
          New only
        </label>
        {list.data && <span className="ml-auto text-sm text-muted tabular">{list.data.total} jobs</span>}
      </div>
      <ErrorNote error={err ?? list.error} />
      {list.loading && !list.data ? (
        <Loading />
      ) : list.data && list.data.matches.length ? (
        <div className="space-y-3">
          {list.data.matches.map((m) => (
            <MatchCard key={m.match_id} m={m} threshold={list.data!.threshold} onDismiss={owner ? dismiss : undefined} />
          ))}
        </div>
      ) : (
        <Empty title="Nothing to show with these filters">
          {view === "shown" ? "Try “All eligible” to see jobs below your threshold and what they are missing." : null}
        </Empty>
      )}
    </>
  );
}

export default function MatchesPage() {
  return (
    <Suspense fallback={<Loading />}>
      <MatchesView />
    </Suspense>
  );
}
