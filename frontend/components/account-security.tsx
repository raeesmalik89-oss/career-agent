"use client";

import { useState } from "react";
import { useMe } from "@/components/shell";
import { Badge, Button, Card, CardHeader, ErrorNote } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface SessionRow {
  id: string;
  current: boolean;
  user_agent: string | null;
  last_active: string;
  expires_at: string;
}

const input = "h-8 w-full rounded-md border border-border bg-bg px-2 text-sm";

/** Password, signed-in devices and two-factor authentication. Secrets are typed by you and never shown back. */
export function AccountSecurity() {
  return (
    <Card className="mt-6">
      <CardHeader title="Account security" sub="Changing your password signs out every other device." />
      <div className="grid gap-6 px-4 py-4 text-sm md:grid-cols-3">
        <PasswordForm />
        <Sessions />
        <TwoFactor />
      </div>
    </Card>
  );
}

function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [err, setErr] = useState<ApiError | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const mismatch = confirm.length > 0 && next !== confirm;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setDone(null);
    try {
      const r = await api.post<{ other_sessions_revoked: number }>("/api/v1/auth/password", {
        current_password: current,
        new_password: next,
      });
      setCurrent("");
      setNext("");
      setConfirm("");
      setDone(`Password changed. ${r.other_sessions_revoked} other device(s) signed out.`);
    } catch (e) {
      setErr(e as ApiError);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2">
      <h3 className="font-medium">Change password</h3>
      <input type="password" autoComplete="current-password" placeholder="Current password" aria-label="Current password" className={input} value={current} onChange={(e) => setCurrent(e.target.value)} />
      <input type="password" autoComplete="new-password" placeholder="New password (12+ characters)" aria-label="New password" className={input} value={next} onChange={(e) => setNext(e.target.value)} />
      <input type="password" autoComplete="new-password" placeholder="Repeat new password" aria-label="Repeat new password" className={input} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      {mismatch && <p className="text-xs text-bad">The two new passwords differ.</p>}
      <Button type="submit" size="sm" disabled={!current || next.length < 12 || next !== confirm}>
        Change password
      </Button>
      <ErrorNote error={err} />
      {done && <p className="text-xs text-good">{done}</p>}
    </form>
  );
}

function Sessions() {
  const list = useApi<SessionRow[]>("/api/v1/auth/sessions");
  const [err, setErr] = useState<ApiError | null>(null);

  async function revoke(id: string) {
    try {
      await api.post(`/api/v1/auth/sessions/${id}/revoke`);
      await list.reload();
    } catch (e) {
      setErr(e as ApiError);
    }
  }
  async function revokeOthers() {
    try {
      await api.post("/api/v1/auth/sessions/revoke-others");
      await list.reload();
    } catch (e) {
      setErr(e as ApiError);
    }
  }
  const others = (list.data ?? []).filter((s) => !s.current).length;

  return (
    <div className="space-y-2">
      <h3 className="font-medium">Signed-in devices</h3>
      <ul className="space-y-1.5">
        {(list.data ?? []).map((s) => (
          <li key={s.id} className="flex items-start justify-between gap-2">
            <span className="min-w-0">
              <span className="block truncate text-xs" title={s.user_agent ?? undefined}>
                {browserName(s.user_agent)} {s.current && <Badge tone="good">this device</Badge>}
              </span>
              <span className="block text-xs text-muted">active {fmtDateTime(s.last_active)}</span>
            </span>
            {!s.current && (
              <button className="shrink-0 text-xs text-bad hover:underline" onClick={() => revoke(s.id)}>
                Sign out
              </button>
            )}
          </li>
        ))}
      </ul>
      {others > 0 && (
        <Button size="sm" onClick={revokeOthers}>
          Sign out {others} other device{others > 1 ? "s" : ""}
        </Button>
      )}
      <ErrorNote error={err ?? list.error} />
    </div>
  );
}

function browserName(ua: string | null): string {
  if (!ua) return "Unknown device";
  const b = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari" : /python|curl|httpx/i.test(ua) ? "Script" : "Browser";
  const os = /Windows/.test(ua) ? "Windows" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Mac OS/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${b} on ${os}` : b;
}

function TwoFactor() {
  const me = useMe();
  const [enabled, setEnabled] = useState(me.totp_enabled);
  const [uri, setUri] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<ApiError | null>(null);
  const secret = uri ? (new URL(uri).searchParams.get("secret") ?? "") : "";

  if (me.role !== "owner") return <div />;

  async function start() {
    setErr(null);
    try {
      setUri((await api.post<{ provisioning_uri: string }>("/api/v1/auth/totp/setup")).provisioning_uri);
    } catch (e) {
      setErr(e as ApiError);
    }
  }
  async function verify() {
    setErr(null);
    try {
      await api.post("/api/v1/auth/totp/verify", { code });
      setEnabled(true);
      setUri(null);
      setCode("");
    } catch (e) {
      setErr(e as ApiError);
    }
  }
  async function disable() {
    setErr(null);
    try {
      await api.post("/api/v1/auth/totp/disable", { password, code });
      setEnabled(false);
      setCode("");
      setPassword("");
    } catch (e) {
      setErr(e as ApiError);
    }
  }
  const codeInput = (
    <input inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="6-digit code" aria-label="Authenticator code" className={input} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
  );

  return (
    <div className="space-y-2">
      <h3 className="font-medium">
        Two-factor sign-in <Badge tone={enabled ? "good" : "warn"}>{enabled ? "on" : "off"}</Badge>
      </h3>
      {!enabled && !uri && (
        <>
          <p className="text-xs text-muted">Adds a 6-digit code from an authenticator app (Google Authenticator, Microsoft Authenticator, Aegis…) to every sign-in.</p>
          <Button size="sm" onClick={start}>
            Set up
          </Button>
        </>
      )}
      {!enabled && uri && (
        <>
          <p className="text-xs text-muted">In your authenticator app choose &quot;enter a setup key&quot;, account &quot;Career Agent&quot;, and type this key:</p>
          <code className="block select-all break-all rounded bg-surface-2 px-2 py-1 font-mono text-xs">{secret.replace(/(.{4})/g, "$1 ").trim()}</code>
          <p className="text-xs text-muted">Then enter the code it shows:</p>
          {codeInput}
          <Button size="sm" variant="primary" onClick={verify} disabled={code.length !== 6}>
            Turn on
          </Button>
        </>
      )}
      {enabled && (
        <>
          <p className="text-xs text-muted">To turn it off, enter your password and a current code.</p>
          <input type="password" autoComplete="current-password" placeholder="Password" aria-label="Password" className={input} value={password} onChange={(e) => setPassword(e.target.value)} />
          {codeInput}
          <Button size="sm" onClick={disable} disabled={!password || code.length !== 6}>
            Turn off
          </Button>
        </>
      )}
      <ErrorNote error={err} />
    </div>
  );
}
