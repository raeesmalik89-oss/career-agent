import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Tone } from "@/lib/format";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

const TONE_TEXT: Record<Tone, string> = {
  good: "text-good",
  ok: "text-accent",
  warn: "text-warn",
  bad: "text-bad",
  muted: "text-faint",
};
const TONE_CHIP: Record<Tone, string> = {
  good: "bg-good-soft text-good",
  ok: "bg-accent-soft text-accent",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  muted: "bg-surface-2 text-muted",
};
const TONE_BAR: Record<Tone, string> = {
  good: "bg-good",
  ok: "bg-accent",
  warn: "bg-warn",
  bad: "bg-bad",
  muted: "bg-faint",
};

export function toneText(t: Tone) {
  return TONE_TEXT[t];
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={cx("rounded-lg border border-border bg-surface", className)}>{children}</section>;
}

export function CardHeader({ title, action, sub }: { title: ReactNode; action?: ReactNode; sub?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
      <div className="min-w-0">
        <h2 className="text-sm font-semibold">{title}</h2>
        {sub && <p className="mt-0.5 text-xs text-muted">{sub}</p>}
      </div>
      {action}
    </div>
  );
}

export function Badge({ tone = "muted", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={cx("inline-flex items-center whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-medium", TONE_CHIP[tone])}
    >
      {children}
    </span>
  );
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-white hover:opacity-90 dark:text-[#0f1115]",
  secondary: "border border-border bg-surface hover:bg-surface-2",
  ghost: "hover:bg-surface-2 text-muted hover:text-text",
  danger: "border border-border bg-surface text-bad hover:bg-bad-soft",
};

export function Button({
  variant = "secondary",
  size = "md",
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  return (
    <button
      {...rest}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-7 px-2.5 text-xs" : "h-9 px-3.5 text-sm",
        VARIANTS[variant],
        className,
      )}
    />
  );
}

export function Bar({ ratio, tone }: { ratio: number; tone: Tone }) {
  const pct = Math.max(0, Math.min(1, ratio)) * 100;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2" aria-hidden>
      <div className={cx("h-full rounded-full", TONE_BAR[tone])} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: Tone }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-4 py-3">
      <div className="text-xs text-muted">{label}</div>
      <div className={cx("tabular mt-1 text-2xl font-semibold", tone && TONE_TEXT[tone])}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-border px-6 py-10 text-center">
      <p className="font-medium">{title}</p>
      {children && <div className="mt-1 text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-8 text-sm text-muted" role="status">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-border border-t-accent" />
      {label}
    </div>
  );
}

export function ErrorNote({ error }: { error: { status?: number; detail?: string; message?: string } | null }) {
  if (!error) return null;
  return (
    <div className="rounded-md border border-bad/30 bg-bad-soft px-3 py-2 text-sm text-bad" role="alert">
      {error.detail ?? error.message}
      {error.status ? ` (HTTP ${error.status})` : ""}
    </div>
  );
}

export function PageHeader({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold">{title}</h1>
        {sub && <div className="mt-1 text-sm text-muted">{sub}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Disclaimer({ text }: { text: string }) {
  return <p className="text-xs text-muted">{text}</p>;
}
