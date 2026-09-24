"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icon } from "@/components/icons";
import { useCanEdit } from "@/components/shell";
import { Badge, Button, Card, CardHeader, Empty, ErrorNote, PageHeader } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { AiReport, AiStatus } from "@/lib/types";
import { useApi } from "@/lib/use-api";

interface TailorOut {
  application_id: string;
  job_id: string;
  ai_report: AiReport | null;
  ai_error: string | null;
}

const input = "mt-1.5 h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm shadow-soft";
const MIN = 100;

export default function TailorPage() {
  const owner = useCanEdit();
  const router = useRouter();
  const ai = useApi<AiStatus>(owner ? "/api/v1/ai/status" : null);
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [useAi, setUseAi] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [aiError, setAiError] = useState<{ id: string; message: string } | null>(null);

  if (!owner) return <Empty title="Only the owner can tailor resumes" />;
  const aiOn = ai.data && ai.data.provider !== "off";
  const provider = ai.data?.providers.find((p) => p.key === ai.data?.provider);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setAiError(null);
    try {
      const out = await api.post<TailorOut>("/api/v1/tailor", {
        title: title.trim(),
        company: company.trim(),
        description: text.trim(),
        url: url.trim() || null,
        use_ai: Boolean(aiOn && useAi),
      });
      if (out.ai_error) setAiError({ id: out.application_id, message: out.ai_error });
      else router.push(`/applications/${out.application_id}`);
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Tailor my CV"
        sub="Paste any job you found (LinkedIn, Rozee, a company site, a referral). You get a CV and cover letter tailored to it, built only from your verified facts."
      />
      <ErrorNote error={err} />
      {err?.detail?.includes("import your resume") && (
        <p className="-mt-2 mb-4 text-sm">
          First <Link href="/profile" className="font-medium text-accent hover:underline">upload your CV on Profile &amp; facts</Link>.
        </p>
      )}
      {aiError && (
        <Card className="mb-5 border-warn/40 p-4">
          <p className="text-sm">
            <span className="font-medium text-warn">The AI step failed:</span> {aiError.message}
          </p>
          <p className="mt-1 text-sm text-muted">Your fact-based tailored CV is ready anyway. You can retry the AI rewrite from the application page.</p>
          <Button className="mt-3" variant="primary" onClick={() => router.push(`/applications/${aiError.id}`)}>
            Open the tailored application →
          </Button>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <form onSubmit={submit} className="lg:col-span-2">
          <Card>
            <CardHeader title="The job" sub="Copy the whole posting: responsibilities, requirements and nice-to-haves." />
            <div className="space-y-4 px-5 py-5 text-sm">
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block font-medium">
                  Job title
                  <input required minLength={2} maxLength={300} className={input} placeholder="DevOps Engineer" value={title} onChange={(e) => setTitle(e.target.value)} />
                </label>
                <label className="block font-medium">
                  Company
                  <input required maxLength={300} className={input} placeholder="Acme Health" value={company} onChange={(e) => setCompany(e.target.value)} />
                </label>
              </div>
              <label className="block font-medium">
                Link to the posting <span className="font-normal text-muted">(optional)</span>
                <input type="url" className={input} placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} />
              </label>
              <label className="block font-medium">
                Job description
                <textarea
                  required
                  minLength={MIN}
                  maxLength={50000}
                  rows={14}
                  className="mt-1.5 w-full rounded-lg border border-border bg-surface p-3 text-sm leading-relaxed shadow-soft"
                  placeholder="Paste the full job posting here…"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
                <span className={text.trim().length < MIN ? "text-xs text-faint" : "text-xs text-good"}>
                  {text.trim().length < MIN ? `${MIN - text.trim().length} more characters needed` : `${text.trim().length.toLocaleString()} characters`}
                </span>
              </label>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
                <label className={aiOn ? "flex items-center gap-2" : "flex items-center gap-2 text-faint"}>
                  <input type="checkbox" disabled={!aiOn} checked={Boolean(aiOn && useAi)} onChange={(e) => setUseAi(e.target.checked)} />
                  Rewrite with AI {aiOn && provider ? `(${provider.label})` : "(off)"}
                </label>
                <Button type="submit" variant="primary" disabled={busy || text.trim().length < MIN || !title.trim() || !company.trim()} className="h-10 px-5">
                  <Icon name="sparkles" />
                  {busy ? (aiOn && useAi ? "Tailoring with AI… (up to a minute)" : "Tailoring…") : "Tailor my CV"}
                </Button>
              </div>
            </div>
          </Card>
        </form>

        <div className="space-y-4">
          <Card>
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  AI rewriting {aiOn ? <Badge tone="good">on</Badge> : <Badge>off</Badge>}
                </span>
              }
            />
            <div className="space-y-2 px-5 py-4 text-sm">
              {aiOn && provider ? (
                <>
                  <p>
                    {provider.label} · <span className="font-mono text-xs">{ai.data?.model}</span>
                  </p>
                  {!ai.data?.ready && <p className="text-warn">No API key stored yet: add it in Settings → AI.</p>}
                  <p className="text-xs text-muted">{provider.privacy}</p>
                </>
              ) : (
                <p className="text-muted">
                  Without AI you still get a tailored CV: your most relevant facts, skills and projects first. Turn on a free AI in{" "}
                  <Link href="/settings#ai" className="font-medium text-accent hover:underline">Settings → AI</Link> to also get the wording
                  rewritten for each job.
                </p>
              )}
            </div>
          </Card>
          <Card>
            <CardHeader title="What happens" />
            <ol className="space-y-3 px-5 py-4 text-sm">
              {[
                ["The job is saved and scored", "like any scanned job, with its Estimated Fit Score."],
                ["A CV is built from your facts", "the skills, bullets and projects that matter for this job come first."],
                ["AI rewrites the wording", "if turned on. Every line is checked again: anything your facts don't support is thrown away and your wording is kept."],
                ["You review and approve", "then download the CV and cover letter and apply on the employer's site. Nothing is sent for you."],
              ].map(([t, d], i) => (
                <li key={t} className="flex gap-3">
                  <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent">{i + 1}</span>
                  <span>
                    <span className="font-medium">{t}:</span> <span className="text-muted">{d}</span>
                  </span>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      </div>
    </>
  );
}
