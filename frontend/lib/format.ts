import type { Fact } from "./types";

export const COMPONENT_LABELS: Record<string, string> = {
  skills: "Skills",
  experience: "Experience",
  github_evidence: "Project / GitHub evidence",
  education_certs: "Education & certifications",
  role_seniority: "Role & seniority",
  location_remote: "Location & remote",
  domain: "Domain",
};

export const KNOCKOUT_LABELS: Record<string, string> = {
  pk_ineligible: "Not open to Pakistan",
  pk_unknown: "Pakistan eligibility unknown",
  location: "Outside your cities",
  clearance: "Security clearance",
  visa: "No visa sponsorship",
  seniority: "Too senior",
  experience: "Too many years required",
};

export type Tone = "good" | "ok" | "warn" | "bad" | "muted";

export function scoreTone(score: number, threshold: number, hidden = false): Tone {
  if (hidden) return "muted";
  if (score >= threshold) return "good";
  if (score >= threshold - 15) return "warn";
  return "bad";
}

export function ratioTone(ratio: number): Tone {
  return ratio >= 0.8 ? "good" : ratio >= 0.5 ? "warn" : "bad";
}

export function fmtScore(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function daysAgo(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "date unknown";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "date unknown";
  const days = Math.floor((now.getTime() - d.getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

export function fmtSalary(s: { min: number; max: number | null; currency: string | null } | null): string | null {
  if (!s) return null;
  const n = (v: number) => (v >= 1000 ? `${Math.round(v / 1000)}k` : String(v));
  const cur = s.currency ?? "";
  return s.max && s.max !== s.min ? `${cur} ${n(s.min)}–${n(s.max)}` : `${cur} ${n(s.min)}`;
}

export function humanize(key: string): string {
  return key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v : null;
}

/** One-line title for a fact, whatever its type. */
export function factTitle(f: Fact): string {
  const d = f.data;
  switch (f.fact_type) {
    case "experience":
      return [str(d.title), str(d.organization)].filter(Boolean).join(" · ") || f.fact_key;
    case "education":
      return [str(d.qualification), str(d.institution)].filter(Boolean).join(" · ") || f.fact_key;
    case "certification":
      return [str(d.name), str(d.issuer)].filter(Boolean).join(" · ") || f.fact_key;
    case "project":
      return str(d.name) ?? f.fact_key;
    case "skill_claim":
      return str(d.name) ?? f.fact_key;
    case "achievement":
      return str(d.text) ?? f.fact_key;
    case "personal":
    case "preference":
      return `${humanize(String(d.field ?? f.fact_key))}: ${String(d.value ?? "")}`;
    default:
      return f.fact_key;
  }
}

/** Short secondary line: dates, evidence level, etc. */
export function factSubtitle(f: Fact): string | null {
  const d = f.data;
  const parts: string[] = [];
  if (f.fact_type === "experience") {
    if (d.start || d.end) parts.push(`${d.start ?? "?"} – ${d.end ?? "?"}`);
    if (typeof d.months === "number") parts.push(`${d.months} months`);
    if (d.is_training) parts.push("training programme");
    if (str(d.sector)) parts.push(String(d.sector));
  } else if (f.fact_type === "education") {
    if (str(d.date)) parts.push(String(d.date));
    if (str(d.grade)) parts.push(`grade ${d.grade}`);
  } else if (f.fact_type === "certification") {
    if (str(d.issued)) parts.push(`issued ${d.issued}`);
    if (str(d.credential_id)) parts.push(`ID ${d.credential_id}`);
  } else if (f.fact_type === "skill_claim") {
    if (str(d.evidence)) parts.push(d.evidence === "applied" ? "used in experience/projects" : "listed only");
    if (Array.isArray(d.implied_by) && d.implied_by.length) parts.push(`implied by ${d.implied_by.join(", ")}`);
  } else if (f.fact_type === "project") {
    if (Array.isArray(d.technologies)) parts.push(`${d.technologies.length} technologies`);
  } else if (f.fact_type === "achievement") {
    if (str(d.context)) parts.push(String(d.context));
  }
  return parts.length ? parts.join(" · ") : null;
}

export function factSources(f: Fact): string[] {
  return (f.source_ref.sources ?? []).map((s) => {
    if (typeof s.label === "string") return s.page ? `${s.label}, p.${s.page}` : s.label;
    if (typeof s.repo === "string") return `GitHub: ${s.repo}`;
    if (s.entered_by) return "entered by you";
    return "source";
  });
}
