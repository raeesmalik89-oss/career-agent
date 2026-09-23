"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

function safeNext(raw: string | null): string {
  // Only same-site paths: never redirect to another origin after login.
  return raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/";
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [needTotp, setNeedTotp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/v1/auth/login", { email, password, ...(needTotp ? { totp_code: totp } : {}) });
      router.replace(safeNext(params.get("next")));
    } catch (err) {
      if (err instanceof ApiError && err.detail === "totp_required") {
        setNeedTotp(true);
        setError(null);
      } else if (err instanceof ApiError && err.status === 401) {
        setError("Email or password is not correct.");
      } else {
        setError(err instanceof ApiError ? err.detail : "Could not reach the server. Is the backend running?");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-lg border border-border bg-surface p-6">
        <h1 className="text-lg font-semibold">Career Agent</h1>
        <p className="mt-1 text-sm text-muted">Sign in to review your matches.</p>
        <label className="mt-5 block text-sm font-medium" htmlFor="email">
          Email
        </label>
        <input
          id="email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mt-1 h-9 w-full rounded-md border border-border bg-bg px-3 text-sm"
        />
        <label className="mt-3 block text-sm font-medium" htmlFor="password">
          Password
        </label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mt-1 h-9 w-full rounded-md border border-border bg-bg px-3 text-sm"
        />
        {needTotp && (
          <>
            <label className="mt-3 block text-sm font-medium" htmlFor="totp">
              6-digit code from your authenticator
            </label>
            <input
              id="totp"
              inputMode="numeric"
              pattern="\d{6}"
              autoComplete="one-time-code"
              required
              value={totp}
              onChange={(e) => setTotp(e.target.value)}
              className="mt-1 h-9 w-full rounded-md border border-border bg-bg px-3 text-sm tracking-widest"
            />
          </>
        )}
        {error && (
          <p className="mt-3 text-sm text-bad" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" disabled={busy} className="mt-5 w-full">
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
