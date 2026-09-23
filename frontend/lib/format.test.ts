import { describe, expect, it } from "vitest";
import { daysAgo, factSources, factSubtitle, factTitle, fmtSalary, fmtScore, scoreTone } from "./format";
import type { Fact } from "./types";

const fact = (fact_type: string, data: Record<string, unknown>, sources: Record<string, unknown>[] = []): Fact => ({
  id: "1",
  fact_type,
  fact_key: "k",
  data,
  source_type: "resume",
  source_ref: { sources },
  review_status: "pending",
  confidence: "high",
});

describe("scores", () => {
  it("tones scores against the threshold and mutes hidden jobs", () => {
    expect(scoreTone(85, 80)).toBe("good");
    expect(scoreTone(70, 80)).toBe("warn");
    expect(scoreTone(50, 80)).toBe("bad");
    expect(scoreTone(95, 80, true)).toBe("muted");
  });
  it("never rounds a score across the threshold", () => {
    expect(fmtScore(79.5)).toBe("79.5");
    expect(fmtScore(80)).toBe("80");
  });
});

describe("facts", () => {
  it("summarises each fact type", () => {
    const exp = fact("experience", { title: "Trainee", organization: "Acme", start: "2024-08", end: "2025-08", months: 13, is_training: true, sector: "tech" });
    expect(factTitle(exp)).toBe("Trainee · Acme");
    expect(factSubtitle(exp)).toBe("2024-08 – 2025-08 · 13 months · training programme · tech");
    expect(factTitle(fact("skill_claim", { name: "Kubernetes" }))).toBe("Kubernetes");
    expect(factSubtitle(fact("skill_claim", { evidence: "listed", implied_by: [] }))).toBe("listed only");
    expect(factTitle(fact("personal", { field: "linkedin", value: "x" }))).toBe("Linkedin: x");
  });
  it("names the source document", () => {
    const f = fact("education", {}, [{ label: "CV", page: 2 }, { repo: "r" }, { entered_by: "user" }]);
    expect(factSources(f)).toEqual(["CV, p.2", "GitHub: r", "entered by you"]);
  });
});

describe("dates and money", () => {
  it("describes age", () => {
    const now = new Date("2026-09-23T12:00:00Z");
    expect(daysAgo("2026-09-23T01:00:00Z", now)).toBe("today");
    expect(daysAgo("2026-09-22T01:00:00Z", now)).toBe("yesterday");
    expect(daysAgo("2026-09-13T12:00:00Z", now)).toBe("10 days ago");
    expect(daysAgo(null, now)).toBe("date unknown");
  });
  it("shows salary only when the source gave one", () => {
    expect(fmtSalary(null)).toBeNull();
    expect(fmtSalary({ min: 60000, max: 80000, currency: "USD" })).toBe("USD 60k–80k");
    expect(fmtSalary({ min: 300000, max: null, currency: "PKR" })).toBe("PKR 300k");
  });
});
