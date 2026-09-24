"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Me } from "@/lib/types";
import { useApi } from "@/lib/use-api";
import { Icon, type IconName, Logo } from "./icons";
import { Loading, cx } from "./ui";

const NAV: { group: string; items: { href: string; label: string; icon: IconName; admin?: boolean }[] }[] = [
  { group: "", items: [{ href: "/", label: "Dashboard", icon: "home" }] },
  {
    group: "Job search",
    items: [
      { href: "/tailor", label: "Tailor my CV", icon: "sparkles" },
      { href: "/matches", label: "Matches", icon: "target" },
      { href: "/jobs", label: "All jobs", icon: "briefcase" },
      { href: "/applications", label: "Applications", icon: "send" },
    ],
  },
  {
    group: "Grow",
    items: [
      { href: "/interview", label: "Interview practice", icon: "mic" },
      { href: "/skills", label: "Skills & learning", icon: "book" },
    ],
  },
  {
    group: "Your evidence",
    items: [
      { href: "/profile", label: "Profile & facts", icon: "user" },
      { href: "/github", label: "GitHub", icon: "github" },
    ],
  },
  {
    group: "System",
    items: [
      { href: "/automation", label: "Automation", icon: "zap" },
      { href: "/activity", label: "Activity", icon: "activity" },
      { href: "/settings", label: "Settings", icon: "settings" },
      { href: "/users", label: "Users", icon: "users", admin: true },
    ],
  },
];

const MeContext = createContext<Me | null>(null);

export function useMe(): Me {
  const me = useContext(MeContext);
  if (!me) throw new Error("useMe outside the app shell");
  return me;
}

/** Can change their own data (CV, facts, applications, settings): the administrator and members. */
export function useCanEdit(): boolean {
  const r = useMe().role;
  return r === "owner" || r === "member";
}

/** Functions that affect everyone: job sources, users and invites, system health and backups. */
export function useIsAdmin(): boolean {
  return useMe().role === "owner";
}

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

const THEMES = ["system", "light", "dark"] as const;
const THEME_ICON = { system: "monitor", light: "sun", dark: "moon" } as const;

function ThemeToggle() {
  const [theme, setTheme] = useState<(typeof THEMES)[number]>("system");
  useEffect(() => {
    const t = document.documentElement.dataset.theme;
    setTheme(t === "light" || t === "dark" ? t : "system");
  }, []);
  function next() {
    const t = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
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
    <button
      onClick={next}
      className="grid h-9 w-9 place-items-center rounded-lg text-muted transition hover:bg-surface-2 hover:text-text"
      title={`Theme: ${theme} (click to change)`}
      aria-label={`Colour theme: ${theme}`}
    >
      <Icon name={THEME_ICON[theme]} className="h-[18px] w-[18px]" />
    </button>
  );
}

/** Unread notifications, refreshed every minute and whenever the page changes. */
function NotificationBell({ pathname }: { pathname: string }) {
  const [unread, setUnread] = useState<number | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .get<{ unread: number }>("/api/v1/notifications/unread-count")
        .then((r) => alive && setUnread(r.unread))
        .catch(() => undefined);
    void load();
    const t = setInterval(load, 60_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [pathname]);
  const active = pathname.startsWith("/notifications");
  return (
    <Link
      href="/notifications"
      className={cx(
        "relative grid h-9 w-9 place-items-center rounded-lg transition hover:bg-surface-2",
        active ? "bg-surface-2 text-text" : "text-muted hover:text-text",
      )}
      aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
      title="Notifications"
    >
      <Icon name="bell" className="h-[18px] w-[18px]" />
      {unread ? (
        <span className="absolute right-1 top-1 grid h-4 min-w-4 place-items-center rounded-full bg-accent px-1 text-[10px] font-semibold leading-none text-accent-contrast tabular ring-2 ring-surface">
          {unread > 99 ? "99+" : unread}
        </span>
      ) : null}
    </Link>
  );
}

function Sidebar({ me, pathname, onNavigate, onLogout }: { me: Me; pathname: string; onNavigate: () => void; onLogout: () => void }) {
  const initials = me.display_name
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return (
    <div className="flex h-full flex-col bg-sidebar text-sidebar-text">
      <Link href="/" onClick={onNavigate} className="flex items-center gap-2.5 px-5 pb-3 pt-5">
        <Logo />
        <span className="text-[15px] font-semibold tracking-tight text-white">Career Agent</span>
      </Link>
      <nav className="sidebar-scroll flex-1 space-y-4 overflow-y-auto px-3 py-1" aria-label="Main">
        {NAV.map((g) => (
          <div key={g.group || "top"}>
            {g.group && (
              <div className="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-sidebar-muted">{g.group}</div>
            )}
            <ul className="space-y-0.5">
              {g.items.filter((n) => !n.admin || me.role === "owner").map((n) => {
                const active = isActive(pathname, n.href);
                return (
                  <li key={n.href}>
                    <Link
                      href={n.href}
                      onClick={onNavigate}
                      aria-current={active ? "page" : undefined}
                      className={cx(
                        "group relative flex items-center gap-3 rounded-lg px-3 py-[7px] text-[13.5px] font-medium transition",
                        active ? "bg-sidebar-active text-white" : "text-sidebar-text/80 hover:bg-white/5 hover:text-white",
                      )}
                    >
                      {active && <span className="absolute inset-y-2 left-0 w-[3px] rounded-r bg-[#818cf8]" aria-hidden />}
                      <Icon
                        name={n.icon}
                        className={cx("h-[18px] w-[18px] shrink-0", active ? "text-[#a5b4fc]" : "text-sidebar-muted group-hover:text-sidebar-text")}
                      />
                      {n.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
      <div className="border-t border-white/5 p-3">
        <div className="flex items-center gap-3 rounded-lg px-2 py-2">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-gradient-to-br from-[#818cf8] to-[#4f46e5] text-xs font-semibold text-white">
            {initials || "?"}
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-white">{me.display_name}</div>
            <div className="truncate text-xs text-sidebar-muted" title={me.email}>
              {me.role === "owner" ? `Admin · ${me.email}` : me.role === "member" ? me.email : `${me.role} · ${me.email}`}
            </div>
          </div>
          <button
            onClick={onLogout}
            className="grid h-8 w-8 place-items-center rounded-lg text-sidebar-muted transition hover:bg-white/5 hover:text-white"
            title="Sign out"
            aria-label="Sign out"
          >
            <Icon name="logout" />
          </button>
        </div>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const me = useApi<Me>("/api/v1/auth/me");
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (me.error?.status === 401) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [me.error, pathname, router]);

  useEffect(() => setMenuOpen(false), [pathname]);

  async function logout() {
    await api.post("/api/v1/auth/logout").catch(() => undefined);
    router.replace("/login");
  }

  if (!me.data) {
    return (
      <div className="grid min-h-screen place-items-center px-4">
        {me.error && me.error.status !== 401 ? (
          <div className="max-w-md rounded-xl border border-border bg-surface p-6 text-center shadow-card">
            <p className="font-medium text-bad">Cannot reach the API</p>
            <p className="mt-1 text-sm text-muted">
              {me.error.detail}. Start it with start-career-agent.cmd, then reload this page.
            </p>
          </div>
        ) : (
          <Loading />
        )}
      </div>
    );
  }

  const current = NAV.flatMap((g) => g.items).find((n) => isActive(pathname, n.href));

  return (
    <MeContext.Provider value={me.data}>
      <div className="min-h-screen lg:pl-64">
        {/* desktop sidebar */}
        <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 lg:block">
          <Sidebar me={me.data} pathname={pathname} onNavigate={() => undefined} onLogout={logout} />
        </aside>

        {/* mobile drawer */}
        {menuOpen && (
          <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
            <button className="absolute inset-0 bg-black/50 backdrop-blur-[2px]" onClick={() => setMenuOpen(false)} aria-label="Close menu" />
            <aside className="absolute inset-y-0 left-0 w-72 max-w-[85%] shadow-pop">
              <Sidebar me={me.data} pathname={pathname} onNavigate={() => setMenuOpen(false)} onLogout={logout} />
            </aside>
          </div>
        )}

        <header className="sticky top-0 z-20 border-b border-border bg-surface/85 backdrop-blur supports-[backdrop-filter]:bg-surface/70">
          <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4 sm:px-6 lg:px-8">
            <button
              className="grid h-9 w-9 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-text lg:hidden"
              onClick={() => setMenuOpen(true)}
              aria-label="Open menu"
            >
              <Icon name="menu" className="h-5 w-5" />
            </button>
            <div className="flex min-w-0 items-center gap-2 text-sm lg:hidden">
              <Logo className="h-6 w-6" />
              <span className="truncate font-semibold">{current?.label ?? "Career Agent"}</span>
            </div>
            <div className="hidden min-w-0 items-center gap-2 text-sm text-muted lg:flex">
              <span>Career Agent</span>
              <span className="text-faint">/</span>
              <span className="truncate font-medium text-text">
                {pathname.startsWith("/notifications") ? "Notifications" : pathname.startsWith("/reports") ? "Daily reports" : (current?.label ?? "")}
              </span>
            </div>
            <div className="ml-auto flex items-center gap-1">
              <NotificationBell pathname={pathname} />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</main>
      </div>
    </MeContext.Provider>
  );
}
