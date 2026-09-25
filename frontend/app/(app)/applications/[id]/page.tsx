"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/icons";
import { useCanEdit } from "@/components/shell";
import { Badge, Button, Card, CardHeader, ErrorNote, Loading, PageHeader, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { STATUS_TONE, fmtDateTime, fmtScore, humanize } from "@/lib/format";
import type { AiReport, AiStatus, AnswerSuggestions, ApplicationAnswerRow, ApplicationDetail, CheckItem } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const CHECK_TONE = { valid: "good", needs_approval: "warn", unsupported: "bad" } as const;
const CHECK_LABEL = { valid: "checked", needs_approval: "review", unsupported: "unsupported" } as const;
const PRE_SUBMIT = ["prepared", "pending_approval", "failed"];
const PLACEHOLDER = /\[[^\]]{3,}\]/;

/** Empty, or still has [bracketed] text that only you can fill. */
function needsInput(text: string) {
  return !text.trim() || PLACEHOLDER.test(text);
}

/** An option replaces the [bracketed] part (e.g. in the cover letter), or the whole answer. */
function fillWith(current: string, option: string) {
  return PLACEHOLDER.test(current) ? current.replace(PLACEHOLDER, option) : option;
}

// One AI request at a time: free tiers limit tokens per minute.
let queue: Promise<unknown> = Promise.resolve();
function queued<T>(fn: () => Promise<T>): Promise<T> {
  const p = queue.then(fn, fn);
  queue = p.catch(() => undefined);
  return p;
}

function fetchSuggestions(appId: string, answerId: string, refresh = false) {
  return queued(() => api.post<AnswerSuggestions>(`/api/v1/applications/${appId}/answers/${answerId}/suggest`, { refresh }));
}

export default function ApplicationPage() {
  const { id } = useParams<{ id: string }>();
  const owner = useCanEdit();
  const res = useApi<ApplicationDetail>(`/api/v1/applications/${id}`);
  const ai = useApi<AiStatus>(owner ? "/api/v1/ai/status" : null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [filling, setFilling] = useState<string | null>(null);

  async function rewriteWithAi() {
    setAiBusy(true);
    await act(() => api.post<ApplicationDetail>(`/api/v1/applications/${id}/ai-tailor`));
    setAiBusy(false);
  }

  /** Put the AI's first suggestion into every answer that still needs you. You review them before approving. */
  async function autofill(targets: ApplicationAnswerRow[]) {
    setBusy(true);
    setErr(null);
    try {
      let detail: ApplicationDetail | null = null;
      for (const [i, t] of targets.entries()) {
        setFilling(`${i + 1} of ${targets.length}`);
        const s = t.suggestions ?? (await fetchSuggestions(id, t.id));
        detail = await api.patch<ApplicationDetail>(`/api/v1/applications/${id}/answers/${t.id}`, {
          answer: fillWith(t.answer, s.options[0].text),
          ai_pick: true,
        });
      }
      if (detail) res.setData(detail);
    } catch (e) {
      setErr(e as ApiError);
      await res.reload();
    } finally {
      setFilling(null);
      setBusy(false);
    }
  }

  async function act(fn: () => Promise<ApplicationDetail>) {
    setBusy(true);
    setErr(null);
    try {
      res.setData(await fn());
    } catch (e) {
      setErr(e as ApiError);
      await res.reload();
    } finally {
      setBusy(false);
    }
  }

  if (res.loading && !res.data) return <Loading />;
  if (!res.data) return <ErrorNote error={res.error} />;
  const a = res.data;
  const editable = owner && PRE_SUBMIT.includes(a.status);
  const checks = new Map((a.resume_validation?.items ?? []).map((c) => [c.path, c]));
  const counts = a.resume_validation?.counts ?? {};
  const aiOn = Boolean(ai.data && ai.data.provider !== "off");
  const gaps = a.answers.filter((x) => x.suggest && needsInput(x.answer));

  return (
    <>
      <Link href="/applications" className="text-sm text-muted hover:text-text">
        ← Applications
      </Link>
      <PageHeader
        title={a.job.title}
        sub={
          <span className="flex flex-wrap items-center gap-2">
            <Link href={`/jobs/${a.job.id}`} className="hover:underline">
              {a.job.company}
              {a.job.location ? ` · ${a.job.location}` : ""}
            </Link>
            <Badge tone={STATUS_TONE[a.status] ?? "muted"}>{humanize(a.status)}</Badge>
            {a.score !== null && <span className="tabular">score {fmtScore(a.score)}/100</span>}
          </span>
        }
        actions={
          <>
            <a className="inline-flex h-9 items-center rounded-md border border-border bg-surface px-3 text-sm hover:bg-surface-2" href={`/api/v1/applications/${a.id}/resume.docx`}>
              Resume .docx
            </a>
            <a className="inline-flex h-9 items-center rounded-md border border-border bg-surface px-3 text-sm hover:bg-surface-2" href={`/api/v1/applications/${a.id}/cover-letter.docx`}>
              Cover letter .docx
            </a>
            {a.application_url && (
              <a
                className="inline-flex h-9 items-center rounded-md px-3 text-sm font-medium text-accent hover:bg-accent-soft"
                href={a.application_url}
                target="_blank"
                rel="noopener noreferrer nofollow"
              >
                Open posting ↗
              </a>
            )}
          </>
        }
      />
      <ErrorNote error={err} />

      {editable && (
        <Card className="mb-6 p-4">
          {a.blockers.length ? (
            <>
              <p className="text-sm font-medium">Before you can approve:</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-bad">
                {a.blockers.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-sm text-good">Ready to approve. Approving does not send anything: you submit it yourself on the employer's site.</p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {ai.data && ai.data.provider !== "off" ? (
              <Button variant="primary" disabled={busy} onClick={rewriteWithAi} title={`Rewrite the resume and cover letter with ${ai.data.provider}`}>
                <Icon name="sparkles" />
                {aiBusy ? "AI is rewriting… (up to a minute)" : a.ai ? "Rewrite again with AI" : "Rewrite with AI"}
              </Button>
            ) : (
              ai.data && (
                <Link href="/settings#ai" className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-dashed border-border-strong px-4 text-sm font-medium text-muted hover:text-text">
                  <Icon name="sparkles" /> Turn on free AI rewriting
                </Link>
              )
            )}
            {aiOn && gaps.length > 0 && (
              <Button
                disabled={busy}
                onClick={() => autofill(gaps)}
                title="Fill each answer that needs you with the AI's first suggestion. You can change any of them before approving."
              >
                <Icon name="zap" />
                {filling ? `Filling ${filling}…` : `Auto-fill ${gaps.length} answer${gaps.length === 1 ? "" : "s"} with AI`}
              </Button>
            )}
            <Button variant={a.ai || !ai.data || ai.data.provider === "off" ? "primary" : "secondary"} disabled={busy || a.blockers.length > 0} onClick={() => act(() => api.post(`/api/v1/applications/${a.id}/approve`))}>
              Approve package
            </Button>
            <Button
              disabled={busy}
              title="Rebuild from your current facts. Your edits to answers are replaced."
              onClick={() => confirm("Rebuild the package from your current facts? Your edited answers will be replaced.") && act(() => api.post(`/api/v1/applications/${a.id}/rebuild`))}
            >
              Rebuild from facts
            </Button>
            <Button variant="danger" disabled={busy} onClick={() => confirm("Withdraw this application?") && act(() => api.post(`/api/v1/applications/${a.id}/reject`, { reason: null }))}>
              Withdraw
            </Button>
          </div>
        </Card>
      )}

      {owner && a.next_statuses.length > 0 && (
        <Card className="mb-6 p-4">
          <p className="text-sm">
            {a.status === "awaiting_manual_submit"
              ? "Approved. Open the posting, upload the resume, paste the answers below, submit, then mark it here."
              : "Track what happens next:"}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {a.next_statuses.map((s) => (
              <Button
                key={s}
                size="sm"
                variant={s === "applied" ? "primary" : s === "withdrawn" || s === "rejected" ? "danger" : "secondary"}
                disabled={busy}
                onClick={() => act(() => api.post(`/api/v1/applications/${a.id}/status`, { status: s }))}
              >
                {s === "applied" ? "I submitted it" : humanize(s)}
              </Button>
            ))}
          </div>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          <h2 className="text-sm font-semibold">Answers and cover letter</h2>
          {a.answers.map((ans) => (
            <AnswerCard key={ans.id} ans={ans} editable={editable} aiOn={aiOn} appId={a.id} onSaved={(d) => res.setData(d)} onError={setErr} />
          ))}
        </div>

        <div className="space-y-4 lg:col-span-2">
          {a.ai && <AiReportCard report={a.ai} />}
          <Card>
            <CardHeader
              title="Tailored resume"
              sub={`${counts.valid ?? 0} checked · ${counts.needs_approval ?? 0} to review · ${counts.unsupported ?? 0} unsupported`}
            />
            {a.resume ? <ResumePreview resume={a.resume} checks={checks} /> : <p className="px-4 py-3 text-sm text-muted">No resume.</p>}
          </Card>
          {a.policy.submission && (
            <Card>
              <CardHeader title="Policy decision" sub={`${humanize(a.policy.submission.outcome)} · rules ${a.policy.submission.policy_version}`} />
              <ul className="divide-y divide-border text-xs">
                {[...(a.policy.prepare?.trace ?? []), ...a.policy.submission.trace].map((t, i) => (
                  <li key={i} className="flex gap-2 px-4 py-1.5">
                    <span className={t.passed ? "text-good" : "text-muted"}>{t.passed ? "✓" : "✗"}</span>
                    <span className="font-medium">{humanize(t.rule)}</span>
                    <span className="ml-auto text-right text-muted">{t.detail}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <Card>
            <CardHeader title="History" />
            <ul className="space-y-1 px-4 py-3 text-xs">
              {a.events.map((e, i) => (
                <li key={i} className="flex justify-between gap-2">
                  <span>{humanize(e.type)}</span>
                  <span className="text-muted">
                    {e.actor} · {fmtDateTime(e.at)}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </>
  );
}

function AnswerCard({
  ans,
  editable,
  aiOn,
  appId,
  onSaved,
  onError,
}: {
  ans: ApplicationAnswerRow;
  editable: boolean;
  aiOn: boolean;
  appId: string;
  onSaved: (d: ApplicationDetail) => void;
  onError: (e: ApiError) => void;
}) {
  const [text, setText] = useState(ans.answer);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [picked, setPicked] = useState<number | null>(null);
  const [sugg, setSugg] = useState<AnswerSuggestions | null>(ans.suggestions ?? null);
  const [suggBusy, setSuggBusy] = useState(false);
  const [suggErr, setSuggErr] = useState<string | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    setText(ans.answer);
    setPicked(null);
  }, [ans.answer]);
  useEffect(() => setSugg(ans.suggestions ?? null), [ans.suggestions]);
  const dirty = text !== ans.answer;
  const long = ans.question === "Cover letter" || ans.category === "open_ended";
  const canSuggest = editable && aiOn && Boolean(ans.suggest);

  async function loadSuggestions(refresh = false) {
    setSuggBusy(true);
    setSuggErr(null);
    try {
      setSugg(await fetchSuggestions(appId, ans.id, refresh));
    } catch (e) {
      setSuggErr(e instanceof ApiError ? e.detail : "Could not get suggestions.");
    } finally {
      setSuggBusy(false);
    }
  }

  // an answer that still needs you gets its options straight away (once; the server caches them)
  const autoAsked = useRef(false);
  useEffect(() => {
    if (canSuggest && !autoAsked.current && !ans.suggestions && needsInput(ans.answer)) {
      autoAsked.current = true;
      void loadSuggestions();
    }
  }, [canSuggest]);

  function pick(i: number) {
    if (!sugg) return;
    setText(fillWith(ans.answer, sugg.options[i].text));
    setPicked(i);
  }

  function writeOwn() {
    const at = Math.max(0, text.search(PLACEHOLDER));
    setText(text.replace(PLACEHOLDER, ""));
    setPicked(null);
    requestAnimationFrame(() => {
      box.current?.focus();
      box.current?.setSelectionRange(at, at);
    });
  }

  async function save() {
    setBusy(true);
    try {
      onSaved(
        await api.patch<ApplicationDetail>(`/api/v1/applications/${appId}/answers/${ans.id}`, { answer: text, ai_pick: picked !== null }),
      );
    } catch (e) {
      onError(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(ans.answer);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: the text is still selectable */
    }
  }

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{ans.question}</span>
        <Badge>{humanize(ans.category)}</Badge>
        <Badge tone={CHECK_TONE[ans.validation_status]}>{CHECK_LABEL[ans.validation_status]}</Badge>
        {ans.ai && (
          <Badge tone="ok" title="Drafted by AI from your facts and the job posting. Read it and make it yours.">
            ✨ AI
          </Badge>
        )}
        {editable && ans.suggest && needsInput(ans.answer) && <Badge tone="warn">needs you</Badge>}
        {ans.approved && <Badge tone="good">approved</Badge>}
        <button onClick={copy} className="ml-auto text-xs text-accent hover:underline" disabled={!ans.answer}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      {ans.validation_notes.length > 0 && (
        <ul className="mt-1 text-xs text-muted">
          {ans.validation_notes.map((n) => (
            <li key={n}>• {n}</li>
          ))}
        </ul>
      )}
      {canSuggest && (
        <SuggestionPanel
          sugg={sugg}
          busy={suggBusy}
          error={suggErr}
          picked={picked}
          open={needsInput(ans.answer)}
          onAsk={() => loadSuggestions(sugg !== null)}
          onPick={pick}
          onWriteOwn={writeOwn}
        />
      )}
      {editable ? (
        <>
          <textarea
            ref={box}
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={long ? 12 : 2}
            aria-label={ans.question}
            className={cx("mt-2 w-full rounded-md border bg-bg p-2 text-sm", /\[[^\]]{3,}\]/.test(text) ? "border-warn" : "border-border")}
          />
          {dirty && (
            <div className="mt-1 flex gap-2">
              <Button size="sm" variant="primary" disabled={busy} onClick={save}>
                Save
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setText(ans.answer);
                  setPicked(null);
                }}
              >
                Undo
              </Button>
            </div>
          )}
        </>
      ) : (
        <p className="mt-2 whitespace-pre-wrap text-sm">{ans.answer || <span className="text-faint">(not used)</span>}</p>
      )}
    </Card>
  );
}

function SuggestionPanel({
  sugg,
  busy,
  error,
  picked,
  open,
  onAsk,
  onPick,
  onWriteOwn,
}: {
  sugg: AnswerSuggestions | null;
  busy: boolean;
  error: string | null;
  picked: number | null;
  open: boolean;
  onAsk: () => void;
  onPick: (i: number) => void;
  onWriteOwn: () => void;
}) {
  const [shown, setShown] = useState(open);
  useEffect(() => setShown(open), [open]);

  if (!shown)
    return (
      <button
        className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
        onClick={() => {
          setShown(true);
          if (!sugg) onAsk();
        }}
      >
        <Icon name="sparkles" className="h-3.5 w-3.5" /> {sugg ? "Show AI suggestions" : "Suggest with AI"}
      </button>
    );

  return (
    <div className="mt-3 rounded-xl border border-accent/30 bg-accent-soft/40 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Icon name="sparkles" className="h-4 w-4 text-accent" />
        <span className="text-sm font-medium">{sugg?.kind === "salary" ? "Suggested salary answers" : "Suggested answers"}</span>
        <span className="text-xs text-muted">pick one to fill the box, or write your own</span>
        <button className="ml-auto text-muted hover:text-text" onClick={() => setShown(false)} aria-label="Hide suggestions">
          <Icon name="x" className="h-3.5 w-3.5" />
        </button>
      </div>

      {busy && !sugg && <p className="mt-3 animate-pulse text-sm text-muted">Reading the posting and your profile…</p>}
      {error && <p className="mt-2 text-sm text-bad">{error}</p>}

      {sugg && (
        <ul className={cx("mt-3 space-y-2", busy && "opacity-50")}>
          {sugg.options.map((o, i) => (
            <li key={o.text}>
              <button
                onClick={() => onPick(i)}
                className={cx(
                  "w-full rounded-lg border bg-surface px-3 py-2 text-left text-sm shadow-soft transition-colors hover:border-accent",
                  picked === i ? "border-accent ring-2 ring-accent/30" : "border-border",
                )}
              >
                <span className="flex items-start gap-2">
                  <span
                    className={cx(
                      "mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] font-semibold",
                      picked === i ? "bg-accent text-white" : "bg-surface-2 text-muted",
                    )}
                  >
                    {picked === i ? <Icon name="check" className="h-3 w-3" /> : i + 1}
                  </span>
                  <span className="min-w-0">
                    <span className="block">{o.text}</span>
                    {o.why && <span className="mt-0.5 block text-xs text-muted">{o.why}</span>}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={onWriteOwn}>
          ✎ Write my own
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onAsk}>
          {busy ? "Thinking…" : sugg ? "↻ Different ideas" : "Suggest with AI"}
        </Button>
        {sugg && <span className="ml-auto text-[11px] text-faint">{sugg.model}</span>}
      </div>
      {sugg && (
        <p className="mt-2 text-xs text-muted">
          {sugg.note}
          {picked !== null && " Press Save below to keep it."}
        </p>
      )}
    </div>
  );
}

function Line({ text, check }: { text: string; check?: CheckItem }) {
  const tone = check ? CHECK_TONE[check.status] : undefined;
  return (
    <span
      title={check?.notes.join(" ") || undefined}
      className={cx(tone === "bad" && "bg-bad-soft text-bad", tone === "warn" && check?.notes.some((n) => !n.includes("not verified")) && "bg-warn-soft")}
    >
      {text}
    </span>
  );
}

function ResumePreview({ resume, checks }: { resume: NonNullable<ApplicationDetail["resume"]>; checks: Map<string, CheckItem> }) {
  const h = resume.header;
  return (
    <div className="space-y-3 px-4 py-3 text-xs leading-relaxed">
      <div>
        <p className="text-sm font-semibold">{h.name?.text}</p>
        <p className="text-muted">{["location", "email", "phone", "linkedin", "github"].filter((k) => h[k]).map((k) => h[k].text).join(" | ")}</p>
      </div>
      {resume.summary && (
        <p title={resume.summary.ai && resume.summary.original ? `Your original: ${resume.summary.original}` : undefined}>
          {resume.summary.ai && <AiMark />}
          <Line text={resume.summary.text} check={checks.get("summary")} />
        </p>
      )}
      {resume.skills.map((g, gi) => (
        <p key={g.group}>
          <span className="font-semibold">{g.group}: </span>
          {g.items.map((s, si) => (
            <span key={s.skill}>
              {si > 0 && ", "}
              <Line text={s.text} check={checks.get(`skills.${gi}.${si}`)} />
            </span>
          ))}
        </p>
      ))}
      <Section title="Experience">
        {resume.experience.map((e, ei) => (
          <div key={ei}>
            <p>
              <Line text={e.title} check={checks.get(`experience.${ei}`)} /> <span className="text-muted">| {e.organization.split(",")[0]}
                {e.location ? ` | ${e.location}` : ""} | {e.dates}</span>
            </p>
            <ul className="list-disc pl-4">
              {e.bullets.map((b, bi) => (
                <li key={bi} title={b.ai && b.original ? `Your original: ${b.original}` : undefined}>
                  {b.ai && <AiMark />}
                  <Line text={b.text} check={checks.get(`experience.${ei}.bullets.${bi}`)} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </Section>
      <Section title="Projects">
        {resume.projects.map((p, pi) => (
          <div key={pi}>
            <p className="font-medium">
              {p.name} <span className="font-normal text-muted">| {p.technologies.join(", ")}</span>
            </p>
            <ul className="list-disc pl-4">
              {p.bullets.map((b, bi) => (
                <li key={bi} title={b.ai && b.original ? `Your original: ${b.original}` : undefined}>
                  {b.ai && <AiMark />}
                  <Line text={b.text} check={checks.get(`projects.${pi}.bullets.${bi}`)} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </Section>
      <Section title="Education">
        {resume.education.map((e, i) => (
          <p key={i}>
            {e.qualification}, {e.institution} {e.date && `| ${e.date}`}
          </p>
        ))}
      </Section>
      <Section title="Certifications">
        {resume.certifications.map((c, i) => (
          <p key={i}>{[c.name, c.issuer].filter(Boolean).join(" · ")}</p>
        ))}
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1 font-semibold uppercase tracking-wide text-muted">{title}</p>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function AiMark() {
  return (
    <span className="mr-1 inline-flex items-center rounded bg-accent-soft px-1 text-[10px] font-semibold text-accent" title="Rewritten by AI; hover the line to see your original">
      AI
    </span>
  );
}

function AiReportCard({ report }: { report: AiReport }) {
  const [open, setOpen] = useState(false);
  const kept = report.kept_original;
  return (
    <Card className="border-accent/30">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Icon name="sparkles" className="h-4 w-4 text-accent" /> Rewritten with AI
          </span>
        }
        sub={`${humanize(report.provider)} · ${report.model} · ${report.seconds}s`}
      />
      <div className="space-y-2 px-5 py-3 text-sm">
        <p>
          <span className="font-semibold text-good">{report.lines_rewritten}</span> line{report.lines_rewritten === 1 ? "" : "s"} rewritten and checked
          against your facts.
          {kept.length > 0 && (
            <>
              {" "}
              <span className="font-semibold text-warn">{kept.length}</span> kept your original wording
              {" "}
              <button className="text-accent hover:underline" onClick={() => setOpen(!open)}>
                {open ? "hide why" : "see why"}
              </button>
            </>
          )}
        </p>
        {open && (
          <ul className="space-y-2 text-xs">
            {kept.map((k) => (
              <li key={k.part} className="rounded-lg bg-surface-2 px-3 py-2">
                <div className="font-medium">{humanize(k.part.replaceAll(".", " "))}</div>
                {k.ai_text && <div className="mt-0.5 text-muted line-through decoration-bad/60">{k.ai_text}</div>}
                <div className="mt-0.5 text-bad">{k.reason.join(" ")}</div>
              </li>
            ))}
          </ul>
        )}
        <p className="text-xs text-muted">
          Hover an <AiMark /> line to see your original. &quot;Rebuild from facts&quot; undoes the AI rewrite.
        </p>
      </div>
    </Card>
  );
}
