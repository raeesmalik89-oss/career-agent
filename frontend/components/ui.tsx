import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Tone } from "@/lib/format";
import { Icon, type IconName } from "./icons";

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
  good: "bg-good-soft text-good ring-good/20",
  ok: "bg-accent-soft text-accent ring-accent/20",
  warn: "bg-warn-soft text-warn ring-warn/20",
  bad: "bg-bad-soft text-bad ring-bad/20",
  muted: "bg-surface-2 text-muted ring-border-strong/60",
};
const TONE_DOT: Record<Tone, string> = {
  good: "bg-good",
  ok: "bg-accent",
  warn: "bg-warn",
  bad: "bg-bad",
  muted: "bg-faint",
};
const TONE_BAR = TONE_DOT;

export function toneText(t: Tone) {
  return TONE_TEXT[t];
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={cx("rounded-xl border border-border bg-surface shadow-card", className)}>{children}</section>;
}

export function CardHeader({ title, action, sub }: { title: ReactNode; action?: ReactNode; sub?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-3.5">
      <div className="min-w-0">
        <h2 className="text-[14px] font-semibold">{title}</h2>
        {sub && <p className="mt-0.5 text-xs leading-relaxed text-muted">{sub}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function Badge({ tone = "muted", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11.5px] font-medium ring-1 ring-inset",
        TONE_CHIP[tone],
      )}
    >
      {children}
    </span>
  );
}

/** A small coloured dot, for status lists. */
export function Dot({ tone = "muted" }: { tone?: Tone }) {
  return <span className={cx("inline-block h-2 w-2 shrink-0 rounded-full", TONE_DOT[tone])} aria-hidden />;
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-accent-contrast shadow-soft hover:bg-accent-hover",
  secondary: "border border-border bg-surface text-text shadow-soft hover:border-border-strong hover:bg-surface-2",
  ghost: "text-muted hover:bg-surface-2 hover:text-text",
  danger: "border border-border bg-surface text-bad shadow-soft hover:border-bad/40 hover:bg-bad-soft",
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
        "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-xs" : "h-9 px-4 text-sm",
        VARIANTS[variant],
        className,
      )}
    />
  );
}

export function Bar({ ratio, tone }: { ratio: number; tone: Tone }) {
  const pct = Math.max(0, Math.min(1, ratio)) * 100;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-3" aria-hidden>
      <div className={cx("h-full rounded-full transition-[width] duration-500", TONE_BAR[tone])} style={{ width: `${pct}%` }} />
    </div>
  );
}

const STAT_ICON_BG: Record<Tone, string> = {
  good: "bg-good-soft text-good",
  ok: "bg-accent-soft text-accent",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  muted: "bg-surface-2 text-muted",
};

export function Stat({
  label,
  value,
  sub,
  tone,
  icon,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: Tone;
  icon?: IconName;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4 shadow-card sm:p-5">
      <div className="flex items-start justify-between gap-2">
        <div className="text-[12.5px] font-medium text-muted">{label}</div>
        {icon && (
          <span className={cx("grid h-8 w-8 shrink-0 place-items-center rounded-lg", STAT_ICON_BG[tone ?? "ok"])}>
            <Icon name={icon} />
          </span>
        )}
      </div>
      <div className={cx("tabular mt-1.5 text-[28px] font-semibold leading-none tracking-tight", tone && tone !== "ok" && TONE_TEXT[tone])}>
        {value}
      </div>
      {sub && <div className="mt-2 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function Empty({ title, children, icon = "sparkles" }: { title: string; children?: ReactNode; icon?: IconName }) {
  return (
    <div className="rounded-xl border border-dashed border-border-strong bg-surface/50 px-6 py-12 text-center">
      <span className="mx-auto grid h-11 w-11 place-items-center rounded-full bg-accent-soft text-accent">
        <Icon name={icon} className="h-5 w-5" />
      </span>
      <p className="mt-3 font-semibold">{title}</p>
      {children && <div className="mx-auto mt-1 max-w-md text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2.5 py-10 text-sm text-muted" role="status">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-surface-3 border-t-accent" />
      {label}
    </div>
  );
}

export function ErrorNote({ error }: { error: { status?: number; detail?: string; message?: string } | null }) {
  if (!error) return null;
  return (
    <div className="mb-4 flex items-start gap-2 rounded-lg border border-bad/25 bg-bad-soft px-3.5 py-2.5 text-sm text-bad" role="alert">
      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-bad" aria-hidden />
      <span>
        {error.detail ?? error.message}
        {error.status ? ` (HTTP ${error.status})` : ""}
      </span>
    </div>
  );
}

export function PageHeader({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0 max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {sub && <div className="mt-1.5 text-sm leading-relaxed text-muted">{sub}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Disclaimer({ text }: { text: string }) {
  return <p className="text-xs text-muted">{text}</p>;
}
