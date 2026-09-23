"use client";

import { useEffect, useState } from "react";
import { useIsOwner } from "@/components/shell";
import { Button, Card, CardHeader, ErrorNote, Loading, PageHeader, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { COMPONENT_LABELS, humanize } from "@/lib/format";
import { useApi } from "@/lib/use-api";

const FAMILIES = ["devops", "cloud", "sre", "aiops", "ai_engineer", "ai_platform", "mlops", "devsecops", "kubernetes", "platform", "cloud_ai_infra", "sre_ai"];
const LEVELS = ["intern", "entry", "junior", "mid", "senior", "staff", "principal"];

// Only the fields this page edits are typed; everything else is sent back unchanged.
interface SettingsDoc {
  version: number;
  preferences: {
    cities: string[];
    accept_remote: boolean;
    accept_hybrid: boolean;
    target_role_families: string[];
    target_seniority: string[];
    min_fit_score: number;
    daily_min_jobs_scanned: number;
    willing_to_relocate: boolean;
    needs_visa_sponsorship: boolean;
    [k: string]: unknown;
  };
  scoring_weights: Record<string, number>;
  policy: {
    knockout_pk_eligibility_unknown: boolean;
    knockout_seniority_gap_levels: number;
    knockout_experience_multiple: number;
    [k: string]: unknown;
  };
  [k: string]: unknown;
}

export default function SettingsPage() {
  const owner = useIsOwner();
  const loaded = useApi<SettingsDoc>("/api/v1/settings");
  const [s, setS] = useState<SettingsDoc | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [rescored, setRescored] = useState<string | null>(null);

  useEffect(() => {
    if (loaded.data) setS(loaded.data);
  }, [loaded.data]);

  if (!s) return loaded.error ? <ErrorNote error={loaded.error} /> : <Loading />;
  const weightSum = Object.values(s.scoring_weights).reduce((a, b) => a + (Number(b) || 0), 0);
  const weightsOk = Math.abs(weightSum - 100) < 1e-6;
  const dirty = JSON.stringify(s) !== JSON.stringify(loaded.data);

  const pref = <K extends keyof SettingsDoc["preferences"]>(k: K, v: SettingsDoc["preferences"][K]) =>
    setS({ ...s, preferences: { ...s.preferences, [k]: v } });
  const pol = <K extends keyof SettingsDoc["policy"]>(k: K, v: SettingsDoc["policy"][K]) =>
    setS({ ...s, policy: { ...s.policy, [k]: v } });
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  async function save() {
    setBusy(true);
    setErr(null);
    setRescored(null);
    try {
      const { version: _v, ...body } = s!;
      const out = await api.put<SettingsDoc>("/api/v1/settings", body);
      loaded.setData(out);
      setS(out);
      setSaved(out.version);
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  async function rescore() {
    setBusy(true);
    try {
      const out = await api.post<{ counts: Record<string, number>; threshold: number }>("/api/v1/matches/run");
      setRescored(`Re-scored ${out.counts.scored ?? 0} jobs: ${out.counts.qualifying ?? 0} at or above ${out.threshold}.`);
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  const num = "h-8 w-20 rounded-md border border-border bg-bg px-2 text-sm tabular disabled:opacity-60";
  return (
    <>
      <PageHeader
        title="Settings"
        sub={`Version ${s.version}. Every save creates a new version and an audit entry.`}
        actions={
          owner && (
            <>
              {saved !== null && !dirty && (
                <Button onClick={rescore} disabled={busy}>
                  Re-score jobs with these settings
                </Button>
              )}
              <Button variant="primary" onClick={save} disabled={!dirty || !weightsOk || busy}>
                {busy ? "Saving…" : "Save"}
              </Button>
            </>
          )
        }
      />
      <ErrorNote error={err} />
      {saved !== null && !dirty && <p className="mb-3 text-sm text-good">Saved as version {saved}.</p>}
      {rescored && <p className="mb-3 text-sm text-good">{rescored}</p>}

      <fieldset disabled={!owner} className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="What to look for" />
          <div className="space-y-4 px-4 py-4 text-sm">
            <Field label="Show jobs scoring at least" hint="Jobs below this are scored but not shown as matches.">
              <input
                type="number"
                min={0}
                max={100}
                className={num}
                value={s.preferences.min_fit_score}
                onChange={(e) => pref("min_fit_score", Number(e.target.value))}
              />
            </Field>
            <Field label="Role families">
              <Chips options={FAMILIES} value={s.preferences.target_role_families} onToggle={(v) => pref("target_role_families", toggle(s.preferences.target_role_families, v))} />
            </Field>
            <Field label="Seniority you are targeting">
              <Chips options={LEVELS} value={s.preferences.target_seniority} onToggle={(v) => pref("target_seniority", toggle(s.preferences.target_seniority, v))} />
            </Field>
            <Field label="Cities for on-site / hybrid" hint="Comma separated.">
              <input
                className="h-8 w-full rounded-md border border-border bg-bg px-2 text-sm"
                value={s.preferences.cities.join(", ")}
                onChange={(e) => pref("cities", e.target.value.split(",").map((c) => c.trim()).filter(Boolean))}
              />
            </Field>
            <div className="flex flex-wrap gap-x-5 gap-y-2">
              <Check label="Remote" checked={s.preferences.accept_remote} onChange={(v) => pref("accept_remote", v)} />
              <Check label="Hybrid" checked={s.preferences.accept_hybrid} onChange={(v) => pref("accept_hybrid", v)} />
              <Check label="Willing to relocate" checked={s.preferences.willing_to_relocate} onChange={(v) => pref("willing_to_relocate", v)} />
              <Check label="Need visa sponsorship" checked={s.preferences.needs_visa_sponsorship} onChange={(v) => pref("needs_visa_sponsorship", v)} />
            </div>
            <Field label="Minimum postings to scan per day">
              <input
                type="number"
                min={1}
                className={num}
                value={s.preferences.daily_min_jobs_scanned}
                onChange={(e) => pref("daily_min_jobs_scanned", Number(e.target.value))}
              />
            </Field>
          </div>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Score weights"
              sub="Must add up to 100."
              action={<span className={cx("tabular text-sm font-medium", weightsOk ? "text-good" : "text-bad")}>{weightSum}</span>}
            />
            <div className="space-y-2 px-4 py-4 text-sm">
              {Object.entries(s.scoring_weights).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between gap-3">
                  <label htmlFor={`w-${k}`}>{COMPONENT_LABELS[k] ?? humanize(k)}</label>
                  <input
                    id={`w-${k}`}
                    type="number"
                    min={0}
                    max={100}
                    className={num}
                    value={v}
                    onChange={(e) => setS({ ...s, scoring_weights: { ...s.scoring_weights, [k]: Number(e.target.value) } })}
                  />
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader title="Knockout rules" sub="A knocked-out job is hidden, with the reason recorded." />
            <div className="space-y-3 px-4 py-4 text-sm">
              <Field label="Hide jobs this many levels above your verified level" hint="Your level comes from dated experience only.">
                <input
                  type="number"
                  min={1}
                  max={6}
                  className={num}
                  value={s.policy.knockout_seniority_gap_levels}
                  onChange={(e) => pol("knockout_seniority_gap_levels", Number(e.target.value))}
                />
              </Field>
              <Field label="Hide jobs asking for more than N× your verified years">
                <input
                  type="number"
                  min={1}
                  step={0.5}
                  className={num}
                  value={s.policy.knockout_experience_multiple}
                  onChange={(e) => pol("knockout_experience_multiple", Number(e.target.value))}
                />
              </Field>
              <Check
                label="Also hide jobs that do not say whether Pakistan is eligible"
                checked={s.policy.knockout_pk_eligibility_unknown}
                onChange={(v) => pol("knockout_pk_eligibility_unknown", v)}
              />
            </div>
          </Card>
        </div>
      </fieldset>
      {!owner && <p className="mt-4 text-sm text-muted">Viewers can read settings but not change them.</p>}
    </>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 font-medium">{label}</div>
      {children}
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-1.5">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function Chips({ options, value, onToggle }: { options: string[]; value: string[]; onToggle: (v: string) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button
          type="button"
          key={o}
          aria-pressed={value.includes(o)}
          onClick={() => onToggle(o)}
          className={cx(
            "rounded-full border px-2.5 py-1 text-xs",
            value.includes(o) ? "border-accent bg-accent-soft text-accent" : "border-border text-muted hover:text-text",
          )}
        >
          {humanize(o)}
        </button>
      ))}
    </div>
  );
}
