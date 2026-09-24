"use client";

import Link from "next/link";
import { useState } from "react";
import { useCanEdit } from "@/components/shell";
import { Badge, Button, Card, Empty, ErrorNote, Loading, PageHeader, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { fmtDateTime, humanize } from "@/lib/format";
import type { NotificationItem, NotificationsOut } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const SEVERITY_TONE = { info: "muted", important: "warn", urgent: "bad" } as const;
const DELIVERY_TONE: Record<string, "good" | "warn" | "bad" | "muted"> = {
  sent: "good",
  deferred: "warn",
  failed: "bad",
  skipped: "muted",
};

export default function NotificationsPage() {
  const owner = useCanEdit();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const res = useApi<NotificationsOut>(`/api/v1/notifications?limit=100${unreadOnly ? "&unread=true" : ""}`);
  const [open, setOpen] = useState<string | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);

  async function markRead(n: NotificationItem) {
    if (n.read_at || !owner) return;
    try {
      const upd = await api.post<NotificationItem>(`/api/v1/notifications/${n.id}/read`);
      res.setData({
        unread: Math.max((res.data?.unread ?? 1) - 1, 0),
        items: res.data!.items.map((i) => (i.id === n.id ? upd : i)),
      });
    } catch (e) {
      setErr(e as ApiError);
    }
  }

  async function readAll() {
    try {
      await api.post("/api/v1/notifications/read-all");
      await res.reload();
    } catch (e) {
      setErr(e as ApiError);
    }
  }

  function toggle(n: NotificationItem) {
    setOpen(open === n.id ? null : n.id);
    void markRead(n);
  }

  return (
    <>
      <PageHeader
        title="Notifications"
        sub="Everything the scheduler and agents want you to know. Email and Telegram copies are optional (Settings → Notifications)."
        actions={
          <>
            <label className="flex items-center gap-1.5 text-sm">
              <input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} />
              Unread only
            </label>
            {owner && (res.data?.unread ?? 0) > 0 && <Button onClick={readAll}>Mark all read</Button>}
          </>
        }
      />
      <ErrorNote error={err ?? res.error} />
      {res.loading && !res.data ? (
        <Loading />
      ) : res.data && res.data.items.length ? (
        <Card>
          <ul className="divide-y divide-border text-sm">
            {res.data.items.map((n) => (
              <li key={n.id} className={cx(!n.read_at && "bg-accent-soft/40")}>
                <button
                  className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-left hover:bg-surface-2"
                  onClick={() => toggle(n)}
                  aria-expanded={open === n.id}
                >
                  <span className={cx("h-2 w-2 shrink-0 rounded-full", n.read_at ? "bg-transparent" : "bg-accent")} aria-hidden />
                  <span className="w-28 shrink-0 text-xs text-muted tabular">{fmtDateTime(n.created_at)}</span>
                  <span className={cx("min-w-0 flex-1", !n.read_at && "font-medium")}>{n.title}</span>
                  {n.severity !== "info" && <Badge tone={SEVERITY_TONE[n.severity]}>{n.severity}</Badge>}
                  <span className="text-xs text-faint">{humanize(n.kind)}</span>
                </button>
                {open === n.id && (
                  <div className="space-y-2 border-t border-border bg-surface-2 px-4 py-3 pl-9">
                    {n.body && <p className="whitespace-pre-wrap text-sm">{n.body}</p>}
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                      {n.link && (
                        <Link href={n.link} className="font-medium text-accent hover:underline">
                          Open →
                        </Link>
                      )}
                      {Object.entries(n.delivered)
                        .filter(([ch]) => ch !== "dashboard")
                        .map(([ch, d]) => (
                          <Badge key={ch} tone={DELIVERY_TONE[d.status ?? ""] ?? "muted"} title={d.error ?? undefined}>
                            {ch}: {d.status ?? "pending"}
                          </Badge>
                        ))}
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
      ) : (
        <Empty title={unreadOnly ? "Nothing unread" : "No notifications yet"}>
          They appear after the first scheduled run. See <Link href="/automation" className="text-accent hover:underline">Automation</Link>.
        </Empty>
      )}
    </>
  );
}
