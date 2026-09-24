"use client";

import { useState } from "react";
import { Icon } from "@/components/icons";
import { useIsAdmin } from "@/components/shell";
import { Badge, Button, Card, CardHeader, Empty, ErrorNote, Loading, PageHeader, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { fmtDate, relTime } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface UserRow {
  id: string;
  email: string;
  display_name: string;
  role: "owner" | "member" | "viewer";
  is_active: boolean;
  totp_enabled: boolean;
  created_at: string;
  last_active: string | null;
  facts: number;
  applications: number;
  is_you: boolean;
}

interface InviteRow {
  id: string;
  role: string;
  email: string | null;
  note: string | null;
  state: "open" | "used" | "revoked" | "expired";
  created_at: string;
  expires_at: string;
  used_at: string | null;
}

const ROLE_LABEL = { owner: "Admin", member: "Member", viewer: "Viewer" } as const;
const STATE_TONE = { open: "ok", used: "good", revoked: "muted", expired: "muted" } as const;
const input = "h-9 w-full rounded-lg border border-border bg-surface px-3 text-sm shadow-soft";

export default function UsersPage() {
  const admin = useIsAdmin();
  const users = useApi<UserRow[]>(admin ? "/api/v1/admin/users" : null);
  const invites = useApi<InviteRow[]>(admin ? "/api/v1/admin/invites" : null);
  const [err, setErr] = useState<ApiError | null>(null);

  if (!admin) return <Empty title="Only the administrator can manage users" icon="shield" />;

  async function update(u: UserRow, patch: Partial<Pick<UserRow, "is_active" | "role">>) {
    if (patch.is_active === false && !confirm(`Deactivate ${u.display_name}? They are signed out at once and cannot sign in.`)) return;
    try {
      await api.patch(`/api/v1/admin/users/${u.id}`, patch);
      await users.reload();
    } catch (e) {
      setErr(e as ApiError);
    }
  }

  async function revoke(i: InviteRow) {
    try {
      await api.del(`/api/v1/admin/invites/${i.id}`);
      await invites.reload();
    } catch (e) {
      setErr(e as ApiError);
    }
  }

  return (
    <>
      <PageHeader
        title="Users"
        sub="Invite people to use Career Agent. Each member gets their own CV, facts, matches, applications and practice. Nobody can see anyone else's data. Jobs are fetched once for everyone with your source keys."
      />
      <ErrorNote error={err ?? users.error ?? invites.error} />

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="space-y-6 lg:col-span-3">
          <Card>
            <CardHeader title="People" sub={users.data ? `${users.data.length} account${users.data.length === 1 ? "" : "s"}` : undefined} />
            {users.loading && !users.data ? (
              <Loading />
            ) : (
              <ul className="divide-y divide-border">
                {(users.data ?? []).map((u) => (
                  <li key={u.id} className={cx("flex flex-wrap items-center gap-3 px-5 py-3.5", !u.is_active && "opacity-60")}>
                    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent">
                      {u.display_name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase()}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{u.display_name}</span>
                        {u.is_you && <Badge tone="ok">you</Badge>}
                        <Badge tone={u.role === "owner" ? "ok" : "muted"}>{ROLE_LABEL[u.role]}</Badge>
                        {!u.is_active && <Badge tone="bad">deactivated</Badge>}
                        {u.totp_enabled && <Badge tone="good">2FA</Badge>}
                      </div>
                      <div className="truncate text-xs text-muted">
                        {u.email} · joined {fmtDate(u.created_at)} · active {u.last_active ? relTime(u.last_active) : "never"} · {u.facts} facts ·{" "}
                        {u.applications} applications
                      </div>
                    </div>
                    {u.role !== "owner" && (
                      <div className="flex shrink-0 items-center gap-2">
                        <select
                          aria-label={`Role of ${u.display_name}`}
                          className="h-8 rounded-lg border border-border bg-surface px-2 text-xs"
                          value={u.role}
                          onChange={(e) => update(u, { role: e.target.value as UserRow["role"] })}
                        >
                          <option value="member">Member</option>
                          <option value="viewer">Viewer (read only)</option>
                        </select>
                        <Button size="sm" variant={u.is_active ? "danger" : "secondary"} onClick={() => update(u, { is_active: !u.is_active })}>
                          {u.is_active ? "Deactivate" : "Reactivate"}
                        </Button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader title="Invitations" sub="Links expire and work once. Revoke any you no longer need." />
            {invites.data && invites.data.length ? (
              <ul className="divide-y divide-border text-sm">
                {invites.data.map((i) => (
                  <li key={i.id} className="flex flex-wrap items-center gap-3 px-5 py-2.5">
                    <Badge tone={STATE_TONE[i.state]}>{i.state}</Badge>
                    <span className="min-w-0 flex-1 truncate">
                      {i.email ?? "anyone with the link"}
                      {i.note ? <span className="text-muted"> · {i.note}</span> : null}
                    </span>
                    <span className="text-xs text-muted">
                      {i.state === "open" ? `expires ${relTime(i.expires_at)}` : i.used_at ? `used ${fmtDate(i.used_at)}` : fmtDate(i.created_at)}
                    </span>
                    {i.state === "open" && (
                      <button className="text-xs text-bad hover:underline" onClick={() => revoke(i)}>
                        Revoke
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-5 py-4 text-sm text-muted">No invitations yet.</p>
            )}
          </Card>
        </div>

        <div className="lg:col-span-2">
          <InviteForm onCreated={() => void invites.reload()} />
        </div>
      </div>
    </>
  );
}

function InviteForm({ onCreated }: { onCreated: () => void }) {
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const [role, setRole] = useState<"member" | "viewer">("member");
  const [days, setDays] = useState(7);
  const [link, setLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setLink(null);
    try {
      const r = await api.post<{ path: string }>("/api/v1/admin/invites", {
        role,
        email: email.trim() || null,
        note: note.trim() || null,
        days,
      });
      setLink(`${window.location.origin}${r.path}`);
      setEmail("");
      setNote("");
      onCreated();
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: the link is selectable */
    }
  }

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Icon name="users" className="h-4 w-4 text-accent" /> Invite someone
          </span>
        }
      />
      <form onSubmit={create} className="space-y-3 px-5 py-4 text-sm">
        <label className="block font-medium">
          Their email <span className="font-normal text-muted">(optional: locks the link to this address)</span>
          <input type="email" className={`mt-1.5 ${input}`} placeholder="friend@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="block font-medium">
          Note <span className="font-normal text-muted">(for you)</span>
          <input className={`mt-1.5 ${input}`} maxLength={200} placeholder="Sara from the AIOps course" value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block font-medium">
            Access
            <select className={`mt-1.5 ${input}`} value={role} onChange={(e) => setRole(e.target.value as "member" | "viewer")}>
              <option value="member">Member (own data)</option>
              <option value="viewer">Viewer (read only)</option>
            </select>
          </label>
          <label className="block font-medium">
            Link valid for
            <select className={`mt-1.5 ${input}`} value={days} onChange={(e) => setDays(Number(e.target.value))}>
              {[1, 3, 7, 14, 30].map((d) => (
                <option key={d} value={d}>
                  {d} day{d > 1 ? "s" : ""}
                </option>
              ))}
            </select>
          </label>
        </div>
        <Button type="submit" variant="primary" disabled={busy} className="w-full">
          {busy ? "Creating…" : "Create invitation link"}
        </Button>
        <ErrorNote error={err} />
        {link && (
          <div className="space-y-2 rounded-lg border border-good/30 bg-good-soft p-3">
            <p className="text-xs font-medium text-good">Send this link to them. It is shown only once.</p>
            <code className="block select-all break-all rounded bg-surface px-2 py-1.5 font-mono text-[11px]">{link}</code>
            <Button size="sm" onClick={copy}>
              {copied ? "Copied" : "Copy link"}
            </Button>
            <p className="text-xs text-muted">
              The link uses this computer&apos;s address. Anyone else can only open it if Career Agent is reachable from their device (e.g. on a
              server; see docs/DEPLOYMENT.md).
            </p>
          </div>
        )}
      </form>
    </Card>
  );
}
