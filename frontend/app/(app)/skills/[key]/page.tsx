"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useIsOwner } from "@/components/shell";
import { Badge, Button, Card, CardHeader, ErrorNote, Loading, PageHeader, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { humanize } from "@/lib/format";
import type { LearningItemRow, MapNode, SkillGuide } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const KIND_ANCHOR: Record<string, string> = {
  explanation: "understand",
  cheatsheet: "cheatsheet",
  commands: "commands",
  lab: "lab",
  troubleshooting: "troubleshooting",
  mini_project: "project",
};

export default function SkillGuidePage() {
  const { key } = useParams<{ key: string }>();
  const owner = useIsOwner();
  const res = useApi<SkillGuide>(`/api/v1/learning/skills/${key}`);
  const [err, setErr] = useState<ApiError | null>(null);

  if (res.loading && !res.data) return <Loading />;
  if (!res.data) return <ErrorNote error={res.error} />;
  const { guide: g, evidence, items, concept_map } = res.data;

  async function planIt() {
    try {
      await api.post("/api/v1/learning/plan", { skills: [key] });
      await res.reload();
    } catch (e) {
      setErr(e as ApiError);
    }
  }

  async function setStatus(item: LearningItemRow, status: LearningItemRow["status"]) {
    try {
      const updated = await api.patch<LearningItemRow>(`/api/v1/learning/items/${item.id}`, { status });
      res.setData({ ...res.data!, items: res.data!.items.map((i) => (i.id === item.id ? updated : i)) });
    } catch (e) {
      setErr(e as ApiError);
    }
  }

  return (
    <>
      <Link href="/skills" className="text-sm text-muted hover:text-text">
        ← Skills
      </Link>
      <PageHeader title={g.title} sub={g.why} />
      <ErrorNote error={err} />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Section id="understand" title="Understand it">
            <p className="text-sm leading-relaxed">{g.explanation}</p>
          </Section>
          {g.cheatsheet && (
            <Section id="cheatsheet" title="Cheat sheet">
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {g.cheatsheet.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </Section>
          )}
          {g.commands && (
            <Section id="commands" title="Commands">
              <ul className="space-y-2 text-sm">
                {g.commands.map((c) => (
                  <li key={c.cmd}>
                    <code className="block overflow-x-auto whitespace-pre rounded bg-surface-2 px-2 py-1 font-mono text-xs">{c.cmd}</code>
                    <span className="text-xs text-muted">{c.what}</span>
                  </li>
                ))}
              </ul>
            </Section>
          )}
          {g.lab && (
            <Section id="lab" title="Hands-on lab">
              <p className="text-sm">
                <span className="font-medium">Goal: </span>
                {g.lab.goal}
              </p>
              <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
                {g.lab.steps.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ol>
              <p className="mt-2 text-sm text-good">Done when: {g.lab.done_when}</p>
            </Section>
          )}
          {g.troubleshooting && (
            <Section id="troubleshooting" title="Troubleshooting">
              <ul className="space-y-2 text-sm">
                {g.troubleshooting.map((t) => (
                  <li key={t.problem}>
                    <span className="font-medium">{t.problem}: </span>
                    <span className="text-muted">{t.fix}</span>
                  </li>
                ))}
              </ul>
            </Section>
          )}
          <Section id="project" title="Mini-project (this is what raises your level)">
            <p className="text-sm font-medium">{g.mini_project.title}</p>
            <p className="mt-1 text-sm">{g.mini_project.brief}</p>
            {g.mini_project.steps.length > 0 && (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
                {g.mini_project.steps.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            )}
            <p className="mt-2 rounded-md bg-accent-soft px-3 py-2 text-sm">
              <span className="font-medium">Evidence it produces: </span>
              {g.mini_project.evidence}
            </p>
          </Section>
          {concept_map && <ConceptMap map={concept_map} />}
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader title="Your evidence" />
            <div className="space-y-2 px-4 py-3 text-sm">
              <p>
                Level:{" "}
                <Badge tone={evidence.level === "strong" || evidence.level === "working" ? "good" : evidence.level ? "warn" : "bad"}>
                  {evidence.level ?? "none"}
                </Badge>
              </p>
              <p className="text-muted">
                CV: {evidence.resume === "applied" ? "used in experience/projects" : evidence.resume === "listed" ? "listed only" : "not on your CV"}
              </p>
              <p className="text-muted">GitHub: {evidence.github_repos.length ? evidence.github_repos.join(", ") : "no code or config found"}</p>
              <p className="text-xs text-muted">{evidence.note}</p>
            </div>
          </Card>

          <Card>
            <CardHeader title="Learning checklist" />
            {items.length ? (
              <ul className="divide-y divide-border text-sm">
                {items.map((i) => (
                  <li key={i.id} className="flex items-center gap-2 px-4 py-2">
                    <input
                      type="checkbox"
                      checked={i.status === "done"}
                      disabled={!owner}
                      onChange={(e) => setStatus(i, e.target.checked ? "done" : "todo")}
                      aria-label={`Mark ${i.title} done`}
                    />
                    <a href={`#${KIND_ANCHOR[i.kind]}`} className={cx("flex-1 hover:underline", i.status === "done" && "text-muted line-through")}>
                      {humanize(i.kind)}
                    </a>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="px-4 py-3 text-sm text-muted">
                {g.curated ? (
                  owner && (
                    <Button size="sm" variant="primary" onClick={planIt}>
                      Add to my learning plan
                    </Button>
                  )
                ) : (
                  "No curated guide for this skill yet."
                )}
              </div>
            )}
          </Card>

          <Card>
            <CardHeader title="Official resources" />
            <ul className="space-y-1 px-4 py-3 text-sm">
              {g.resources.map((r) => (
                <li key={r.url}>
                  <a href={r.url} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                    {r.title} ↗
                  </a>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <Card>
      <div id={id} className="scroll-mt-20">
        <CardHeader title={title} />
      </div>
      <div className="px-4 py-3">{children}</div>
    </Card>
  );
}

function ConceptMap({ map }: { map: NonNullable<SkillGuide["concept_map"]> }) {
  const [copied, setCopied] = useState<string | null>(null);
  async function copy(text: string, what: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(what);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      /* clipboard blocked */
    }
  }
  return (
    <Card>
      <CardHeader
        title="Concept map"
        sub="Click a branch to open or close it."
        action={
          <span className="flex gap-2 text-xs">
            <button className="text-accent hover:underline" onClick={() => copy(map.mermaid, "mermaid")}>
              {copied === "mermaid" ? "Copied" : "Copy Mermaid"}
            </button>
            <button className="text-accent hover:underline" onClick={() => copy(map.markdown, "md")}>
              {copied === "md" ? "Copied" : "Copy Markdown"}
            </button>
          </span>
        }
      />
      <div className="overflow-x-auto px-4 py-3">
        <div className="inline-block rounded-full bg-accent px-3 py-1 text-sm font-semibold text-white dark:text-[#0f1115]">{map.tree.label}</div>
        <ul className="mt-2 space-y-1 border-l border-border pl-4">
          {map.tree.children.map((c) => (
            <Branch key={c.label} node={c} depth={1} />
          ))}
        </ul>
      </div>
    </Card>
  );
}

function Branch({ node, depth }: { node: MapNode; depth: number }) {
  const [open, setOpen] = useState(depth < 2);
  const has = node.children.length > 0;
  return (
    <li className="text-sm">
      <button
        className={cx("flex items-center gap-1.5 rounded px-1 text-left", has ? "hover:bg-surface-2" : "cursor-default", depth === 1 && "font-medium")}
        onClick={() => has && setOpen(!open)}
        aria-expanded={has ? open : undefined}
      >
        <span className="w-3 text-faint" aria-hidden>
          {has ? (open ? "▾" : "▸") : "•"}
        </span>
        {node.label}
      </button>
      {has && open && (
        <ul className="ml-2 space-y-0.5 border-l border-border pl-4">
          {node.children.map((c) => (
            <Branch key={c.label} node={c} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}
