"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Logo } from "@/components/icons";
import { Button } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

interface InviteInfo {
  role: string;
  email: string | null;
  expires_at: string;
}

const input = "mt-1.5 h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm shadow-soft";

function SignupForm() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token") ?? "";
  const [invite, setInvite] = useState<InviteInfo | null>(null);
  const [invalid, setInvalid] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) {
      setInvalid("This page needs an invitation link.");
      return;
    }
    api
      .get<InviteInfo>(`/api/v1/auth/invite?token=${encodeURIComponent(token)}`)
      .then((i) => {
        setInvite(i);
        if (i.email) setEmail(i.email);
      })
      .catch((e) => setInvalid(e instanceof ApiError ? e.detail : "Could not check the invitation."));
  }, [token]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/v1/auth/signup", { token, display_name: name.trim(), email: email.trim(), password });
      router.replace("/profile");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not create the account.");
    } finally {
      setBusy(false);
    }
  }

  const mismatch = confirm.length > 0 && password !== confirm;
  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-8 flex items-center gap-2.5">
          <Logo className="h-9 w-9" />
          <span className="text-lg font-semibold tracking-tight">Career Agent</span>
        </div>
        {invalid ? (
          <div className="rounded-xl border border-border bg-surface p-6 shadow-card">
            <h1 className="text-xl font-semibold">Invitation not valid</h1>
            <p className="mt-2 text-sm text-muted">{invalid} Ask the person who invited you for a new link.</p>
            <Link href="/login" className="mt-4 inline-block text-sm font-medium text-accent hover:underline">
              Already have an account? Sign in →
            </Link>
          </div>
        ) : (
          <form onSubmit={submit} className="rounded-xl border border-border bg-surface p-6 shadow-card sm:p-8">
            <h1 className="text-2xl font-semibold tracking-tight">Create your account</h1>
            <p className="mt-1.5 text-sm text-muted">
              You have been invited{invite ? ` as a ${invite.role}` : ""}. Your CV, matches and applications are private to you.
            </p>
            <label className="mt-6 block text-sm font-medium" htmlFor="name">
              Your name
            </label>
            <input id="name" required minLength={2} maxLength={200} autoComplete="name" className={input} value={name} onChange={(e) => setName(e.target.value)} />
            <label className="mt-4 block text-sm font-medium" htmlFor="email">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="username"
              readOnly={Boolean(invite?.email)}
              className={`${input} ${invite?.email ? "bg-surface-2 text-muted" : ""}`}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <label className="mt-4 block text-sm font-medium" htmlFor="password">
              Password <span className="font-normal text-muted">(12+ characters)</span>
            </label>
            <input id="password" type="password" required minLength={12} autoComplete="new-password" className={input} value={password} onChange={(e) => setPassword(e.target.value)} />
            <label className="mt-4 block text-sm font-medium" htmlFor="confirm">
              Repeat password
            </label>
            <input id="confirm" type="password" required autoComplete="new-password" className={input} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            {mismatch && <p className="mt-1 text-xs text-bad">The passwords differ.</p>}
            {error && (
              <p className="mt-4 rounded-lg border border-bad/25 bg-bad-soft px-3 py-2 text-sm text-bad" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" variant="primary" disabled={busy || !invite || password.length < 12 || password !== confirm} className="mt-6 h-10 w-full">
              {busy ? "Creating your account…" : "Create account"}
            </Button>
            <p className="mt-4 text-center text-xs text-faint">Next, you&apos;ll upload your CV and review what was found.</p>
          </form>
        )}
      </div>
    </main>
  );
}

export default function SignupPage() {
  return (
    <Suspense>
      <SignupForm />
    </Suspense>
  );
}
