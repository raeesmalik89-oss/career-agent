"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Icon, type IconName, Logo } from "@/components/icons";
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

  const input =
    "mt-1.5 h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm shadow-soft placeholder:text-faint";
  return (
    <main className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <section className="relative hidden overflow-hidden bg-sidebar p-12 text-white lg:flex lg:flex-col">
        <div
          className="pointer-events-none absolute inset-0 opacity-90"
          style={{
            background:
              "radial-gradient(60% 50% at 20% 10%, rgba(129,140,248,.35), transparent 70%), radial-gradient(50% 40% at 90% 90%, rgba(79,70,229,.45), transparent 70%)",
          }}
          aria-hidden
        />
        <div className="relative flex items-center gap-2.5">
          <Logo className="h-9 w-9" />
          <span className="text-lg font-semibold tracking-tight">Career Agent</span>
        </div>
        <div className="relative mt-auto max-w-md">
          <h2 className="text-3xl font-semibold leading-tight tracking-tight">Your job search, run like a pipeline.</h2>
          <p className="mt-3 text-[15px] leading-relaxed text-sidebar-text">
            Daily scans, honest fit scores backed by your real evidence, applications you approve, and interview practice
            built from your own CV.
          </p>
          <ul className="mt-8 space-y-3 text-sm text-sidebar-text">
            {[
              ["target", "Explainable Estimated Resume-to-Job Fit Scores"],
              ["shield", "Nothing is ever sent without your approval"],
              ["chart", "Skill gaps ranked by what employers ask for"],
            ].map(([icon, text]) => (
              <li key={text} className="flex items-center gap-3">
                <span className="grid h-8 w-8 place-items-center rounded-lg bg-white/10 text-[#c7d2fe]">
                  <Icon name={icon as IconName} />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </div>
        <p className="relative mt-12 text-xs text-sidebar-muted">Private workspace · runs on your own computer</p>
      </section>

      <section className="flex items-center justify-center px-4 py-12 sm:px-8">
        <form onSubmit={submit} className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <Logo className="h-8 w-8" />
            <span className="text-lg font-semibold tracking-tight">Career Agent</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">Welcome back</h1>
          <p className="mt-1.5 text-sm text-muted">Sign in to review your matches and applications.</p>
          <label className="mt-8 block text-sm font-medium" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            placeholder="you@example.com"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={input}
          />
          <label className="mt-4 block text-sm font-medium" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={input}
          />
          {needTotp && (
            <>
              <label className="mt-4 block text-sm font-medium" htmlFor="totp">
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
                className={`${input} tracking-[0.3em]`}
              />
            </>
          )}
          {error && (
            <p className="mt-4 rounded-lg border border-bad/25 bg-bad-soft px-3 py-2 text-sm text-bad" role="alert">
              {error}
            </p>
          )}
          <Button type="submit" variant="primary" disabled={busy} className="mt-6 h-10 w-full">
            {busy ? "Signing in…" : "Sign in"}
          </Button>
          <p className="mt-6 text-center text-xs text-faint">Protected by rate limits, lockout and optional 2FA.</p>
        </form>
      </section>
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
