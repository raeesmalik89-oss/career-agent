"use client";

import { Card, CardHeader, PageHeader } from "@/components/ui";

// Curated career / internship destinations. Big employers run their own portals (they can't be
// auto-scanned), so these are quick links you open yourself. Entries where the exact careers URL
// changes often use a search that always resolves to the current page.
const search = (q: string) => `https://www.google.com/search?q=${encodeURIComponent(q)}`;

type Link = { name: string; href: string; note?: string };
const GROUPS: { group: string; sub: string; links: Link[] }[] = [
  {
    group: "Big tech — internships & new-grad",
    sub: "Apply on their own portals; filter for Intern / Islamabad / Remote.",
    links: [
      { name: "Google Careers", href: "https://careers.google.com/", note: "Students & internships" },
      { name: "Microsoft Careers", href: "https://careers.microsoft.com/", note: "Students & internships" },
      { name: "Amazon Jobs", href: "https://www.amazon.jobs/", note: "Student programs" },
      { name: "Meta Careers", href: "https://www.metacareers.com/" },
      { name: "IBM Careers", href: search("IBM internship careers") },
      { name: "Oracle Careers", href: search("Oracle internship careers") },
    ],
  },
  {
    group: "Remote-friendly DevOps / Cloud / SRE",
    sub: "Companies that hire remotely and lean DevOps/cloud — good fit for your focus.",
    links: [
      { name: "GitLab", href: "https://about.gitlab.com/jobs/", note: "All-remote" },
      { name: "Canonical (Ubuntu)", href: "https://canonical.com/careers", note: "All-remote" },
      { name: "HashiCorp", href: "https://www.hashicorp.com/careers" },
      { name: "Red Hat", href: "https://www.redhat.com/en/jobs" },
      { name: "Cloudflare", href: "https://www.cloudflare.com/careers/" },
      { name: "Datadog", href: search("Datadog careers") },
    ],
  },
  {
    group: "Pakistan software houses",
    sub: "Islamabad / remote-friendly employers. Links open their careers page via search.",
    links: [
      { name: "Systems Limited", href: search("Systems Limited careers Pakistan") },
      { name: "NETSOL Technologies", href: search("NETSOL Technologies careers") },
      { name: "Arbisoft", href: search("Arbisoft careers") },
      { name: "10Pearls", href: search("10Pearls careers Pakistan") },
      { name: "Techlogix", href: search("Techlogix careers") },
      { name: "Confiz", href: search("Confiz careers") },
      { name: "VentureDive", href: search("VentureDive careers") },
      { name: "Devsinc", href: search("Devsinc careers") },
      { name: "i2c", href: search("i2c inc careers Pakistan") },
      { name: "Contour Software", href: search("Contour Software careers Pakistan") },
    ],
  },
  {
    group: "Quick searches (Islamabad + remote)",
    sub: "Live searches that always show the latest openings.",
    links: [
      {
        name: "LinkedIn — DevOps intern, Islamabad",
        href: "https://www.linkedin.com/jobs/search/?keywords=devops%20intern&location=Islamabad%2C%20Pakistan",
      },
      {
        name: "LinkedIn — Cybersecurity, Pakistan (remote)",
        href: "https://www.linkedin.com/jobs/search/?keywords=cyber%20security&location=Pakistan&f_WT=2",
      },
      { name: "Rozee.pk", href: "https://www.rozee.pk/", note: "Pakistan's local board" },
      { name: "Indeed Pakistan", href: "https://pk.indeed.com/" },
    ],
  },
];

export default function OpportunitiesPage() {
  return (
    <div>
      <PageHeader title="Opportunities" sub="Curated internship and job links from top companies — open them yourself to apply." />
      <div className="grid gap-6 lg:grid-cols-2">
        {GROUPS.map((g) => (
          <Card key={g.group}>
            <CardHeader title={g.group} sub={g.sub} />
            <ul className="flex flex-col gap-1 px-4 py-4">
              {g.links.map((l) => (
                <li key={l.name}>
                  <a
                    href={l.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center justify-between rounded-lg px-3 py-2 text-sm hover:bg-surface"
                  >
                    <span className="font-medium">{l.name}</span>
                    <span className="flex items-center gap-2 text-xs text-muted">
                      {l.note}
                      <span aria-hidden>↗</span>
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          </Card>
        ))}
      </div>
      <p className="mt-6 text-xs text-muted">
        Note: Google, Microsoft, LinkedIn and Indeed can&apos;t be auto-scanned (their terms forbid it), so these are
        quick links you open. Your automatic scanner covers the remote job boards and Jooble.
      </p>
    </div>
  );
}
