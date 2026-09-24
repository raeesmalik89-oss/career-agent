"use client";

import { useMemo, useState } from "react";
import { CvUpload } from "@/components/cv-upload";
import { useCanEdit } from "@/components/shell";
import { Badge, Button, Card, CardHeader, Empty, ErrorNote, Loading, PageHeader, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { factSources, factSubtitle, factTitle, humanize } from "@/lib/format";
import type { Fact } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const TYPES = ["experience", "education", "certification", "project", "skill_claim", "achievement", "personal", "preference"];
const TYPE_LABEL: Record<string, string> = { skill_claim: "Skills", personal: "Personal", preference: "Availability" };
const STATUS_TONE = { pending: "warn", verified: "good", rejected: "bad" } as const;

interface Conflict {
  field: string;
  values: { value: unknown; documents: string[] }[];
}

interface ResumeReport {
  experience_summary?: { tech_months_professional: number; tech_months_training: number; healthcare_months: number; note: string };
  missing_evidence?: { skill: string; name: string; detail: string }[];
  weak_sections?: { section: string; issue: string; suggestion: string }[];
}

export default function ProfilePage() {
  const owner = useCanEdit();
  const facts = useApi<Fact[]>("/api/v1/profile/facts");
  const report = useApi<ResumeReport>("/api/v1/resume/intelligence");
  const [type, setType] = useState("experience");
  const [status, setStatus] = useState<"pending" | "verified" | "rejected" | "all">("pending");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [err, setErr] = useState<ApiError | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const counts = useMemo(() => {
    const c: Record<string, { pending: number; total: number }> = {};
    for (const f of facts.data ?? []) {
      c[f.fact_type] ??= { pending: 0, total: 0 };
      c[f.fact_type].total++;
      if (f.review_status === "pending") c[f.fact_type].pending++;
    }
    return c;
  }, [facts.data]);

  const shown = (facts.data ?? []).filter((f) => f.fact_type === type && (status === "all" || f.review_status === status));

  function replace(updated: Fact) {
    if (facts.data) facts.setData(facts.data.map((f) => (f.id === updated.id ? updated : f)));
  }

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setErr(null);
    setNote(null);
    try {
      await fn();
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  const setReview = (f: Fact, review_status: string) =>
    run(async () => replace(await api.patch<Fact>(`/api/v1/profile/facts/${f.id}`, { review_status })));

  const verify = (f: Fact) => run(async () => replace(await api.post<Fact>(`/api/v1/profile/facts/${f.id}/verify`)));

  const resolve = (f: Fact, field: string, value: unknown) =>
    run(async () => {
      const remaining = ((f.data.conflicts as Conflict[]) ?? []).filter((c) => c.field !== field);
      const { conflicts: _drop, ...rest } = f.data;
      const data = { ...rest, [field]: value, ...(remaining.length ? { conflicts: remaining } : {}) };
      replace(
        await api.patch<Fact>(`/api/v1/profile/facts/${f.id}`, {
          data,
          resolve_conflicts: true,
          note: `chose "${String(value)}" for ${field}`,
        }),
      );
    });

  const bulkVerify = () =>
    run(async () => {
      const r = await api.post<{ verified: string[]; skipped: { id: string; reason: string }[] }>(
        "/api/v1/profile/facts/verify-bulk",
        { fact_ids: [...picked] },
      );
      setPicked(new Set());
      await facts.reload();
      setNote(`Verified ${r.verified.length}.${r.skipped.length ? ` Skipped ${r.skipped.length} (${[...new Set(r.skipped.map((s) => s.reason))].join("; ")}).` : ""}`);
    });

  const togglePick = (id: string) =>
    setPicked((p) => {
      const n = new Set(p);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const selectable = shown.filter((f) => f.review_status === "pending" && !f.data.conflicts);
  const allPicked = selectable.length > 0 && selectable.every((f) => picked.has(f.id));
  const exp = report.data?.experience_summary;

  return (
    <>
      <PageHeader
        title="Profile & facts"
        sub="Everything the agents know about you, with the document it came from. Only you can verify a fact. Applications will only auto-submit verified facts."
      />

      {owner && (facts.data && facts.data.length === 0 ? (
        <div className="mb-6">
          <CvUpload onDone={() => void Promise.all([facts.reload(), report.reload()])} />
        </div>
      ) : (
        <details className="group mb-6">
          <summary className="cursor-pointer list-none text-sm font-medium text-accent hover:underline">
            + Upload a new or updated CV
          </summary>
          <div className="mt-3">
            <CvUpload onDone={() => void Promise.all([facts.reload(), report.reload()])} />
          </div>
        </details>
      ))}

      {exp && (
        <div className="mb-5 grid gap-3 md:grid-cols-3">
          <Card className="px-4 py-3">
            <div className="text-xs text-muted">Technology experience</div>
            <div className="mt-1 text-sm">
              <span className="tabular text-lg font-semibold">{exp.tech_months_professional}</span> months professional ·{" "}
              <span className="tabular text-lg font-semibold">{exp.tech_months_training}</span> months training
            </div>
          </Card>
          <Card className="px-4 py-3">
            <div className="text-xs text-muted">Healthcare experience</div>
            <div className="mt-1 tabular text-lg font-semibold">{exp.healthcare_months} months</div>
          </Card>
          <Card className="px-4 py-3">
            <div className="text-xs text-muted">Skills listed without evidence</div>
            <div className="mt-1 tabular text-lg font-semibold">{report.data?.missing_evidence?.length ?? 0}</div>
          </Card>
        </div>
      )}

      <div className="mb-3 flex gap-1 overflow-x-auto border-b border-border" role="tablist">
        {TYPES.filter((t) => counts[t]).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={type === t}
            onClick={() => {
              setType(t);
              setPicked(new Set());
            }}
            className={cx(
              "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm",
              type === t ? "border-accent font-medium" : "border-transparent text-muted hover:text-text",
            )}
          >
            {TYPE_LABEL[t] ?? humanize(t)}
            {counts[t].pending > 0 && <span className="ml-1.5 text-xs text-warn tabular">{counts[t].pending}</span>}
          </button>
        ))}
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value as typeof status)}
          className="h-8 rounded-md border border-border bg-surface px-2 text-sm"
          aria-label="Review status"
        >
          <option value="pending">Pending review</option>
          <option value="verified">Verified</option>
          <option value="rejected">Rejected</option>
          <option value="all">All</option>
        </select>
        {owner && selectable.length > 0 && (
          <>
            <label className="flex items-center gap-1.5 text-sm text-muted">
              <input
                type="checkbox"
                checked={allPicked}
                onChange={() => setPicked(allPicked ? new Set() : new Set(selectable.map((f) => f.id)))}
              />
              Select all shown
            </label>
            <Button size="sm" variant="primary" disabled={!picked.size || busy} onClick={bulkVerify}>
              Verify {picked.size || ""} selected
            </Button>
            <span className="text-xs text-muted">Only tick facts you have read and know are true.</span>
          </>
        )}
      </div>
      {note && <p className="mb-3 text-sm text-good">{note}</p>}
      <ErrorNote error={err ?? facts.error} />

      {facts.loading && !facts.data ? (
        <Loading />
      ) : shown.length ? (
        <div className="space-y-2">
          {shown.map((f) => {
            const conflicts = (f.data.conflicts as Conflict[] | undefined) ?? [];
            const sources = factSources(f);
            return (
              <Card key={f.id} className="px-4 py-3">
                <div className="flex items-start gap-3">
                  {owner && f.review_status === "pending" && !conflicts.length && (
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={picked.has(f.id)}
                      onChange={() => togglePick(f.id)}
                      aria-label={`Select ${factTitle(f)}`}
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{factTitle(f)}</span>
                      <Badge tone={STATUS_TONE[f.review_status]}>{f.review_status}</Badge>
                      {conflicts.length > 0 && <Badge tone="bad">conflict</Badge>}
                    </div>
                    {factSubtitle(f) && <p className="text-xs text-muted">{factSubtitle(f)}</p>}
                    <FactDetail f={f} />
                    {sources.length > 0 && (
                      <p className="mt-1 text-xs text-faint">
                        From: {[...new Set(sources)].slice(0, 4).join(" · ")}
                        {sources.length > 4 ? ` +${sources.length - 4}` : ""}
                      </p>
                    )}
                    {conflicts.map((c) => (
                      <div key={c.field} className="mt-2 rounded-md border border-bad/30 bg-bad-soft/50 p-2 text-sm">
                        <p className="text-xs font-medium text-bad">
                          Your documents disagree on “{humanize(c.field)}”. Which is correct?
                        </p>
                        <div className="mt-1.5 space-y-1">
                          {c.values.map((v) => (
                            <div key={String(v.value)} className="flex flex-wrap items-center gap-2">
                              {owner && (
                                <Button size="sm" disabled={busy} onClick={() => resolve(f, c.field, v.value)}>
                                  Use this
                                </Button>
                              )}
                              <span>{String(v.value)}</span>
                              <span className="text-xs text-muted">({v.documents.join(", ")})</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                  {owner && (
                    <div className="flex shrink-0 gap-1">
                      {f.review_status !== "verified" && !conflicts.length && f.review_status !== "rejected" && (
                        <Button size="sm" disabled={busy} onClick={() => verify(f)}>
                          Verify
                        </Button>
                      )}
                      {f.review_status !== "rejected" ? (
                        <Button size="sm" variant="danger" disabled={busy} onClick={() => setReview(f, "rejected")}>
                          Reject
                        </Button>
                      ) : (
                        <Button size="sm" disabled={busy} onClick={() => setReview(f, "pending")}>
                          Restore
                        </Button>
                      )}
                    </div>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      ) : (
        <Empty title={status === "pending" ? "Nothing waiting for review here" : "No facts with this status"} />
      )}

      {report.data?.weak_sections && report.data.weak_sections.length > 0 && (
        <Card className="mt-6">
          <CardHeader title="CV suggestions" sub="From the Resume Analyzer. Nothing here changes your facts." />
          <ul className="divide-y divide-border text-sm">
            {report.data.weak_sections.map((w) => (
              <li key={w.section + w.issue} className="px-4 py-2">
                <span className="font-medium">{humanize(w.section)}:</span> {w.issue}{" "}
                <span className="text-muted">{w.suggestion}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}

function FactDetail({ f }: { f: Fact }) {
  const d = f.data;
  const list = (Array.isArray(d.responsibilities) ? d.responsibilities : Array.isArray(d.highlights) ? d.highlights : []) as string[];
  const tech = Array.isArray(d.technologies) ? (d.technologies as string[]) : [];
  if (!list.length && !tech.length) return null;
  return (
    <div className="mt-1.5 text-sm">
      {list.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-muted">
          {list.slice(0, 5).map((x) => (
            <li key={x}>{x}</li>
          ))}
          {list.length > 5 && <li className="list-none text-xs">+{list.length - 5} more</li>}
        </ul>
      )}
      {tech.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {tech.map((t) => (
            <Badge key={t}>{t}</Badge>
          ))}
        </div>
      )}
    </div>
  );
}
