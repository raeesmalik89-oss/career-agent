"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Me } from "@/lib/types";
import { useApi } from "@/lib/use-api";
import { Loading, cx } from "./ui";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/matches", label: "Matches" },
  { href: "/applications", label: "Applications" },
  { href: "/jobs", label: "All jobs" },
  { href: "/profile", label: "Profile & facts" },
  { href: "/github", label: "GitHub" },
  { href: "/settings", label: "Settings" },
  { href: "/activity", label: "Activity" },
];

const MeContext = createContext<Me | null>(null);

export function useMe(): Me {
  const me = useContext(MeContext);
  if (!me) throw new Error("useMe outside the app shell");
  return me;
}

export function useIsOwner(): boolean {
  return useMe().role === "owner";
}

function ThemeToggle() {
  const [theme, setTheme] = useState<string>("system");
  useEffect(() => {
    setTheme(document.documentElement.dataset.theme ?? "system");
  }, []);
  function next() {
    const order = ["system", "light", "dark"];
    const t = order[(order.indexOf(theme) + 1) % order.length];
    setTheme(t);
    if (t === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = t;
    try {
      if (t === "system") localStorage.removeItem("theme");
      else localStorage.setItem("theme", t);
    } catch {
      /* storage unavailable: the choice lasts for this page only */
    }
  }
  return (
    <button onClick={next} className="rounded-md px-2 py-1 text-xs text-muted hover:bg-surface-2" title="Colour theme">
      Theme: {theme}
    </button>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const me = useApi<Me>("/api/v1/auth/me");

  useEffect(() => {
    if (me.error?.status === 401) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [me.error, pathname, router]);

  async function logout() {
    await api.post("/api/v1/auth/logout").catch(() => undefined);
    router.replace("/login");
  }

  if (!me.data) {
    return (
      <div className="mx-auto max-w-6xl px-4">
        {me.error && me.error.status !== 401 ? (
          <p className="py-10 text-sm text-bad">
            Cannot reach the API ({me.error.detail}). Start it with start-career-agent.cmd and reload.
          </p>
        ) : (
          <Loading />
        )}
      </div>
    );
  }

  return (
    <MeContext.Provider value={me.data}>
      <header className="sticky top-0 z-10 border-b border-border bg-surface/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4">
          <Link href="/" className="shrink-0 py-3 text-sm font-semibold">
            Career Agent
          </Link>
          <nav className="-mb-px flex min-w-0 flex-1 gap-1 overflow-x-auto" aria-label="Main">
            {NAV.map((n) => {
              const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  aria-current={active ? "page" : undefined}
                  className={cx(
                    "whitespace-nowrap border-b-2 px-2.5 py-3 text-sm",
                    active ? "border-accent font-medium text-text" : "border-transparent text-muted hover:text-text",
                  )}
                >
                  {n.label}
                </Link>
              );
            })}
          </nav>
          <div className="hidden shrink-0 items-center gap-1 md:flex">
            <ThemeToggle />
            <span className="px-1 text-xs text-muted" title={me.data.email}>
              {me.data.display_name}
              {me.data.role !== "owner" ? ` (${me.data.role})` : ""}
            </span>
            <button onClick={logout} className="rounded-md px-2 py-1 text-xs text-muted hover:bg-surface-2">
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
      <footer className="mx-auto flex max-w-6xl items-center justify-between px-4 pb-8 text-xs text-faint md:hidden">
        <ThemeToggle />
        <button onClick={logout}>Sign out</button>
      </footer>
    </MeContext.Provider>
  );
}
