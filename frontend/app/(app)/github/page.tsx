"use client";

import { useState } from "react";
import { Badge, Card, CardHeader, Empty, ErrorNote, Loading, PageHeader, cx } from "@/components/ui";
import { fmtDateTime } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface Repo {
  name: string;
  url: string;
  score: number;
  languages: string[];
  summary: string | null;
  commits: { total?: number; by_owner?: number; by_machine_identity?: number; last?: string };
  has: Record<string, boolean>;
  flags: string[];
  top_skills: string[];
}

interface Report {
  profile: { username: string; repositories: number; last_synced_at: string | null };
  repositories: Repo[];
  resume_vs_github: {
    confirmed: { skill: string; name: string; high_repos: string[]; medium_repos: string[] }[];
    resume_only: { skill: string; name: string; resume_evidence: string; detail: string }[];
    github_only: { skill: string; name: string; high_repos: string[] }[];
  };
  projects: { project: string; repo: string | null; not_found_in_repo: string[]; readme_only: string[]; note: string | null }[];
  recommendations: string[];
}

const HAS = [
  ["has_tests", "tests"],
  ["has_ci", "CI"],
  ["has_docker", "Docker"],
  ["has_kubernetes", "K8s"],
  ["has_iac", "IaC"],
] as const;

export default function GithubPage() {
  const r = useApi<Report>("/api/v1/github/intelligence");
  const [tab, setTab] = useState<"confirmed" | "resume_only" | "github_only">("confirmed");

  if (r.loading && !r.data) return <Loading />;
  if (r.error?.status === 404) return <Empty title="GitHub not analysed yet">Run github-sync from the CLI first.</Empty>;
  if (!r.data) return <ErrorNote error={r.error} />;
  const d = r.data;
  const repos = [...d.repositories].sort((a, b) => b.score - a.score);
  const rvg = d.resume_vs_github;

  return (
    <>
      <PageHeader
        title="GitHub evidence"
        sub={`${d.profile.username} · ${d.profile.repositories} repositories · synced ${fmtDateTime(d.profile.last_synced_at)}. A repository's name is never evidence; only code, config and CI are.`}
      />

      {d.recommendations.length > 0 && (
        <Card className="mb-6">
          <CardHeader title="What to fix" sub="These change how strongly your repos back your CV." />
          <ul className="divide-y divide-border text-sm">
            {d.recommendations.map((t) => (
              <li key={t} className="px-4 py-2">
                {t}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Resume vs GitHub" />
          <div className="flex gap-1 border-b border-border px-3" role="tablist">
            {(
              [
                ["confirmed", `Confirmed (${rvg.confirmed.length})`],
                ["resume_only", `Resume only (${rvg.resume_only.length})`],
                ["github_only", `GitHub only (${rvg.github_only.length})`],
              ] as const
            ).map(([k, label]) => (
              <button
                key={k}
                role="tab"
                aria-selected={tab === k}
                onClick={() => setTab(k)}
                className={cx(
                  "-mb-px border-b-2 px-2 py-2 text-sm",
                  tab === k ? "border-accent font-medium" : "border-transparent text-muted",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <ul className="max-h-96 divide-y divide-border overflow-y-auto text-sm">
            {tab === "confirmed" &&
              rvg.confirmed.map((s) => (
                <li key={s.skill} className="flex justify-between gap-2 px-4 py-2">
                  <span>{s.name}</span>
                  <span className="text-xs text-muted">{s.high_repos.length} repos with code/config</span>
                </li>
              ))}
            {tab === "resume_only" &&
              rvg.resume_only.map((s) => (
                <li key={s.skill} className="px-4 py-2">
                  <div className="flex justify-between gap-2">
                    <span>{s.name}</span>
                    <Badge tone={s.resume_evidence === "applied" ? "warn" : "muted"}>{s.resume_evidence}</Badge>
                  </div>
                  <p className="text-xs text-muted">{s.detail}</p>
                </li>
              ))}
            {tab === "github_only" &&
              rvg.github_only.map((s) => (
                <li key={s.skill} className="px-4 py-2">
                  {s.name} <span className="text-xs text-muted">in {s.high_repos.join(", ")}: consider adding it to your CV</span>
                </li>
              ))}
          </ul>
        </Card>

        <Card>
          <CardHeader title="CV projects checked against repos" />
          <ul className="max-h-[27rem] divide-y divide-border overflow-y-auto text-sm">
            {d.projects.map((p) => (
              <li key={p.project} className="px-4 py-2">
                <div className="flex justify-between gap-2">
                  <span className="font-medium">{p.project}</span>
                  {p.repo ? <Badge tone="good">{p.repo}</Badge> : <Badge tone="warn">no public repo</Badge>}
                </div>
                {p.not_found_in_repo.length > 0 && (
                  <p className="text-xs text-bad">Not found in repo: {p.not_found_in_repo.join(", ")}</p>
                )}
                {p.readme_only.length > 0 && <p className="text-xs text-warn">README only: {p.readme_only.join(", ")}</p>}
                {p.note && <p className="text-xs text-muted">{p.note}</p>}
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <h2 className="mb-3 mt-8 text-sm font-semibold">Repositories</h2>
      <div className="grid gap-3 md:grid-cols-2">
        {repos.map((repo) => (
          <Card key={repo.name} className="p-4">
            <div className="flex items-start justify-between gap-2">
              <a href={repo.url} target="_blank" rel="noopener noreferrer" className="font-medium hover:underline">
                {repo.name}
              </a>
              <span className="tabular text-sm text-muted">{repo.score}</span>
            </div>
            {repo.summary && <p className="mt-1 line-clamp-2 text-xs text-muted">{repo.summary}</p>}
            <div className="mt-2 flex flex-wrap gap-1">
              {HAS.map(([k, label]) => (
                <Badge key={k} tone={repo.has?.[k] ? "good" : "muted"}>
                  {repo.has?.[k] ? "✓" : "–"} {label}
                </Badge>
              ))}
              {repo.flags.map((f) => (
                <Badge key={f} tone="warn">
                  {f}
                </Badge>
              ))}
            </div>
            <p className="mt-2 text-xs text-muted">
              {repo.commits.total ?? 0} commits
              {repo.commits.by_machine_identity ? ` · ${repo.commits.by_machine_identity} under a server identity` : ""}
              {repo.commits.last ? ` · last ${repo.commits.last}` : ""}
            </p>
          </Card>
        ))}
      </div>
    </>
  );
}
