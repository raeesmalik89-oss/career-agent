"use client";

import { useEffect, useState } from "react";
import { AccountSecurity } from "@/components/account-security";
import { useIsOwner } from "@/components/shell";
import { Button, Card, CardHeader, ErrorNote, Loading, PageHeader, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { COMPONENT_LABELS, humanize } from "@/lib/format";
import type { AiStatus } from "@/lib/types";
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
  schedules: {
    enabled: boolean;
    timezone: string;
    morning_scan: string;
    afternoon_analysis: string;
    evening_prep: string;
    weekly_sync: string;
    housekeeping: string;
    delta_scans_enabled: boolean;
    delta_scan: string;
    catch_up_hours: number;
    auto_prepare: boolean;
  };
  ai: { provider: "off" | "groq" | "gemini" | "ollama"; model: string | null; ollama_url: string };
  notifications: {
    dashboard_url: string;
    external_min_severity: "info" | "important" | "urgent";
    quiet_hours_start: number | null;
    quiet_hours_end: number | null;
    email_enabled: boolean;
    email_to: string | null;
    email_from: string | null;
    smtp_host: string | null;
    smtp_port: number;
    smtp_username: string | null;
    daily_digest_email: boolean;
    telegram_enabled: boolean;
    telegram_chat_id: string | null;
  };
  [k: string]: unknown;
}

const CRONS: ["morning_scan" | "afternoon_analysis" | "evening_prep" | "weekly_sync" | "housekeeping", string][] = [
  ["morning_scan", "Morning job scan"],
  ["afternoon_analysis", "Skill-gap analysis"],
  ["evening_prep", "Evening prep + daily report"],
  ["weekly_sync", "Weekly GitHub sync"],
  ["housekeeping", "Housekeeping"],
];

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
  const sch = <K extends keyof SettingsDoc["schedules"]>(k: K, v: SettingsDoc["schedules"][K]) =>
    setS({ ...s, schedules: { ...s.schedules, [k]: v } });
  const ntf = <K extends keyof SettingsDoc["notifications"]>(k: K, v: SettingsDoc["notifications"][K]) =>
    setS({ ...s, notifications: { ...s.notifications, [k]: v } });
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

        <Card>
          <CardHeader title="Automation" sub="Cron format: minute hour day month weekday (0 7 * * * = every day at 07:00)." />
          <div className="space-y-3 px-4 py-4 text-sm">
            <div className="flex flex-col gap-2">
              <Check label="Run pipelines automatically" checked={s.schedules.enabled} onChange={(v) => sch("enabled", v)} />
              <Check
                label="Prepare application packages for new matches (never submits)"
                checked={s.schedules.auto_prepare}
                onChange={(v) => sch("auto_prepare", v)}
              />
            </div>
            <Field label="Time zone">
              <input
                className="h-8 w-56 rounded-md border border-border bg-bg px-2 text-sm"
                value={s.schedules.timezone}
                onChange={(e) => sch("timezone", e.target.value)}
              />
            </Field>
            {CRONS.map(([k, label]) => (
              <div key={k} className="flex items-center justify-between gap-3">
                <label htmlFor={`c-${k}`}>{label}</label>
                <input
                  id={`c-${k}`}
                  className="h-8 w-36 rounded-md border border-border bg-bg px-2 font-mono text-xs"
                  value={s.schedules[k]}
                  onChange={(e) => sch(k, e.target.value)}
                />
              </div>
            ))}
            <div className="flex items-center justify-between gap-3">
              <Check
                label="Extra midday scan (4 more Jooble requests)"
                checked={s.schedules.delta_scans_enabled}
                onChange={(v) => sch("delta_scans_enabled", v)}
              />
              <input
                aria-label="Midday scan schedule"
                disabled={!s.schedules.delta_scans_enabled}
                className="h-8 w-36 rounded-md border border-border bg-bg px-2 font-mono text-xs disabled:opacity-50"
                value={s.schedules.delta_scan}
                onChange={(e) => sch("delta_scan", e.target.value)}
              />
            </div>
            <Field
              label="Catch up missed runs up to this many hours late"
              hint="If the computer was off at 07:00, the scan runs when the scheduler next starts, if still within this window."
            >
              <input
                type="number"
                min={0}
                max={24}
                className={num}
                value={s.schedules.catch_up_hours}
                onChange={(e) => sch("catch_up_hours", Number(e.target.value))}
              />
            </Field>
          </div>
        </Card>

        <AiSettingsCard ai={s.ai} setAi={(ai) => setS({ ...s, ai })} dirty={dirty} owner={owner} />
        <NotificationSettings s={s} ntf={ntf} num={num} dirty={dirty} owner={owner} />
      </fieldset>
      {!owner && <p className="mt-4 text-sm text-muted">Viewers can read settings but not change them.</p>}
      <AccountSecurity />
    </>
  );
}

type AiDoc = SettingsDoc["ai"];

const GET_KEY: Record<string, { url: string; how: string }> = {
  groq: { url: "https://console.groq.com/keys", how: "Sign in at console.groq.com → API Keys → Create API Key (free)." },
  gemini: { url: "https://aistudio.google.com/app/apikey", how: "Sign in at aistudio.google.com → Get API key → Create API key (free)." },
};

function AiSettingsCard({ ai, setAi, dirty, owner }: { ai: AiDoc; setAi: (a: AiDoc) => void; dirty: boolean; owner: boolean }) {
  const status = useApi<AiStatus>(owner ? "/api/v1/ai/status" : null);
  const [test, setTest] = useState<string | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [testing, setTesting] = useState(false);
  const chosen = status.data?.providers.find((p) => p.key === ai.provider);

  async function runTest() {
    setTesting(true);
    setErr(null);
    setTest(null);
    try {
      const r = await api.post<{ ok: boolean; model: string; seconds: number }>("/api/v1/ai/test");
      setTest(r.ok ? `Connected: ${r.model} answered in ${r.seconds}s.` : "Connected, but the model's reply was unexpected.");
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setTesting(false);
    }
  }

  const options: { key: AiDoc["provider"]; label: string; note: string }[] = [
    { key: "off", label: "Off", note: "Fact-based tailoring only" },
    { key: "groq", label: "Groq", note: "Free key · fast · recommended" },
    { key: "gemini", label: "Google Gemini", note: "Free key · good quality" },
    { key: "ollama", label: "Ollama", note: "On this PC · private · slow here" },
  ];

  return (
    <Card className="lg:col-span-2">
      <div id="ai" className="scroll-mt-20" />
      <CardHeader
        title="AI rewriting (free)"
        sub="Rewrites your tailored CV and cover letter for each job. Every AI line is re-checked against your facts; anything unsupported is thrown away."
        action={
          owner && ai.provider !== "off" && (
            <Button size="sm" onClick={runTest} disabled={dirty || testing}>
              {dirty ? "Save before testing" : testing ? "Testing…" : "Test AI"}
            </Button>
          )
        }
      />
      <div className="space-y-4 px-5 py-4 text-sm">
        <div className="grid gap-2 sm:grid-cols-4" role="radiogroup" aria-label="AI provider">
          {options.map((o) => (
            <button
              type="button"
              key={o.key}
              role="radio"
              aria-checked={ai.provider === o.key}
              onClick={() => setAi({ ...ai, provider: o.key, model: null })}
              className={cx(
                "rounded-lg border px-3 py-2.5 text-left transition",
                ai.provider === o.key ? "border-accent bg-accent-soft ring-1 ring-accent" : "border-border hover:border-border-strong",
              )}
            >
              <div className="font-medium">{o.label}</div>
              <div className="text-xs text-muted">{o.note}</div>
            </button>
          ))}
        </div>

        {ai.provider !== "off" && chosen && (
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-3">
              <Field label="Model" hint={`Leave empty for the default (${chosen.default_model}).`}>
                <input
                  className="h-8 w-full rounded-md border border-border bg-bg px-2 font-mono text-xs"
                  placeholder={chosen.default_model}
                  value={ai.model ?? ""}
                  onChange={(e) => setAi({ ...ai, model: e.target.value.trim() || null })}
                />
              </Field>
              {ai.provider === "ollama" && (
                <Field label="Ollama address" hint="Only this computer is allowed. Install from ollama.com, then run: ollama pull llama3.2:3b">
                  <input
                    className="h-8 w-full rounded-md border border-border bg-bg px-2 font-mono text-xs"
                    value={ai.ollama_url}
                    onChange={(e) => setAi({ ...ai, ollama_url: e.target.value.trim() })}
                  />
                </Field>
              )}
              <p className="rounded-lg bg-surface-2 px-3 py-2 text-xs text-muted">{chosen.privacy}</p>
            </div>
            <div className="space-y-3">
              {chosen.needs_key && chosen.secret_name && owner && (
                <>
                  <SecretInput
                    name={chosen.secret_name}
                    label={`${chosen.label} API key`}
                    stored={chosen.key_stored ?? false}
                    onSaved={status.reload}
                  />
                  {GET_KEY[chosen.key] && (
                    <p className="text-xs text-muted">
                      {GET_KEY[chosen.key].how}{" "}
                      <a href={GET_KEY[chosen.key].url} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                        Open ↗
                      </a>
                    </p>
                  )}
                </>
              )}
              {test && <p className="text-xs text-good">{test}</p>}
              <ErrorNote error={err} />
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

type Ntf = SettingsDoc["notifications"];

const orNull = (v: string) => (v.trim() ? v.trim() : null);

function NotificationSettings({
  s,
  ntf,
  num,
  dirty,
  owner,
}: {
  s: SettingsDoc;
  ntf: <K extends keyof Ntf>(k: K, v: Ntf[K]) => void;
  num: string;
  dirty: boolean;
  owner: boolean;
}) {
  const n = s.notifications;
  const stored = useApi<{ smtp_password: boolean; telegram_bot_token: boolean }>(owner ? "/api/v1/notifications/channels" : null);
  const [test, setTest] = useState<Record<string, { status: string | null; error: string | null }> | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const text = "h-8 w-full rounded-md border border-border bg-bg px-2 text-sm";

  async function sendTest() {
    setErr(null);
    setTest(null);
    try {
      setTest(await api.post("/api/v1/notifications/test"));
    } catch (e) {
      setErr(e as ApiError);
    }
  }

  return (
    <Card className="lg:col-span-2">
      <CardHeader
        title="Notifications"
        sub="Everything always appears under the bell icon. Email and Telegram are optional extra copies."
        action={
          owner && (
            <Button size="sm" onClick={sendTest} disabled={dirty}>
              {dirty ? "Save before testing" : "Send test"}
            </Button>
          )
        }
      />
      <div className="grid gap-6 px-4 py-4 text-sm md:grid-cols-3">
        <div className="space-y-3">
          <Field label="Also send to email/Telegram when at least">
            <select
              className="h-8 rounded-md border border-border bg-bg px-2 text-sm"
              value={n.external_min_severity}
              onChange={(e) => ntf("external_min_severity", e.target.value as Ntf["external_min_severity"])}
            >
              <option value="info">info (everything)</option>
              <option value="important">important (matches, packages, problems)</option>
              <option value="urgent">urgent only</option>
            </select>
          </Field>
          <Field label="Quiet hours" hint="Email/Telegram wait until quiet hours end (urgent ones excepted). Leave empty for none.">
            <span className="flex items-center gap-2">
              <input
                type="number"
                min={0}
                max={23}
                aria-label="Quiet hours start"
                className={num}
                value={n.quiet_hours_start ?? ""}
                onChange={(e) => ntf("quiet_hours_start", e.target.value === "" ? null : Number(e.target.value))}
              />
              to
              <input
                type="number"
                min={0}
                max={23}
                aria-label="Quiet hours end"
                className={num}
                value={n.quiet_hours_end ?? ""}
                onChange={(e) => ntf("quiet_hours_end", e.target.value === "" ? null : Number(e.target.value))}
              />
            </span>
          </Field>
          <Field label="Dashboard address used in links">
            <input className={text} value={n.dashboard_url} onChange={(e) => ntf("dashboard_url", e.target.value)} />
          </Field>
        </div>

        <div className="space-y-3">
          <Check label="Email" checked={n.email_enabled} onChange={(v) => ntf("email_enabled", v)} />
          <Field label="Send to">
            <input type="email" className={text} value={n.email_to ?? ""} onChange={(e) => ntf("email_to", orNull(e.target.value))} />
          </Field>
          <Field label="From address">
            <input type="email" className={text} value={n.email_from ?? ""} onChange={(e) => ntf("email_from", orNull(e.target.value))} />
          </Field>
          <div className="flex gap-2">
            <Field label="SMTP server">
              <input className={text} placeholder="smtp.gmail.com" value={n.smtp_host ?? ""} onChange={(e) => ntf("smtp_host", orNull(e.target.value))} />
            </Field>
            <Field label="Port">
              <input type="number" className={num} value={n.smtp_port} onChange={(e) => ntf("smtp_port", Number(e.target.value))} />
            </Field>
          </div>
          <Field label="SMTP username">
            <input className={text} value={n.smtp_username ?? ""} onChange={(e) => ntf("smtp_username", orNull(e.target.value))} />
          </Field>
          {owner && <SecretInput name="smtp_password" label="SMTP password (app password)" stored={stored.data?.smtp_password} onSaved={stored.reload} />}
          <Check label="Email me the daily report" checked={n.daily_digest_email} onChange={(v) => ntf("daily_digest_email", v)} />
        </div>

        <div className="space-y-3">
          <Check label="Telegram" checked={n.telegram_enabled} onChange={(v) => ntf("telegram_enabled", v)} />
          <Field label="Chat ID" hint="Send your bot a message, then open api.telegram.org/bot(token)/getUpdates to see your chat id.">
            <input className={text} value={n.telegram_chat_id ?? ""} onChange={(e) => ntf("telegram_chat_id", orNull(e.target.value))} />
          </Field>
          {owner && (
            <SecretInput name="telegram_bot_token" label="Bot token (from @BotFather)" stored={stored.data?.telegram_bot_token} onSaved={stored.reload} />
          )}
          <ErrorNote error={err} />
          {test && (
            <ul className="space-y-1 text-xs">
              {Object.entries(test).map(([ch, r]) => (
                <li key={ch} className={r.status === "sent" ? "text-good" : "text-bad"}>
                  {ch}: {r.status}
                  {r.error ? ` (${r.error})` : ""}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Card>
  );
}

/** Write-only: the value is sent once, stored encrypted and never shown again. */
function SecretInput({ name, label, stored, onSaved }: { name: string; label: string; stored?: boolean; onSaved: () => Promise<void> }) {
  const [value, setValue] = useState("");
  const [err, setErr] = useState<ApiError | null>(null);
  async function save() {
    setErr(null);
    try {
      await api.put("/api/v1/secrets", { name, value });
      setValue("");
      await onSaved();
    } catch (e) {
      setErr(e as ApiError);
    }
  }
  return (
    <Field label={label} hint={stored ? "Stored encrypted. Enter a new value to replace it." : "Not stored yet."}>
      <span className="flex gap-2">
        <input
          type="password"
          autoComplete="off"
          className="h-8 w-full rounded-md border border-border bg-bg px-2 text-sm"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <Button size="sm" onClick={save} disabled={value.trim().length < 4}>
          Store
        </Button>
      </span>
      <ErrorNote error={err} />
    </Field>
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
