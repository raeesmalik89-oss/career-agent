export interface Me {
  id: string;
  email: string;
  display_name: string;
  role: "owner" | "viewer" | "system";
  totp_enabled: boolean;
  timezone: string;
}

export interface Dashboard {
  label: string;
  disclaimer: string;
  settings_version: number;
  threshold: number;
  matches: { qualifying: number; new: number; below_threshold: number; hidden: number; dismissed: number };
  jobs: {
    scanned_today: number;
    daily_minimum: number;
    unique: number;
    targets: number;
    by_pk_eligibility: Record<string, number>;
  };
  facts: { pending: number; verified: number; rejected: number; conflicts: number };
  github: { username: string | null; repos: number; last_synced_at: string | null };
  metered_sources: { source: string; used: number; quota: number }[];
  recent_runs: { agent: string; status: string; started_at: string; errors: number }[];
}

export interface Salary {
  min: number;
  max: number | null;
  currency: string | null;
  source_text: string | null;
}

export interface JobSummary {
  id: string;
  title: string;
  company: string;
  location: string | null;
  remote_type: string;
  role_family: string | null;
  seniority: string | null;
  pk_eligibility: "eligible" | "ineligible" | "unknown";
  pk_eligibility_evidence: string | null;
  experience_required_years: number | null;
  salary: Salary | null;
  posted_date: string | null;
  url: string;
  application_url: string | null;
  content_version: number;
  first_seen_at: string;
  last_seen_at: string;
}

export interface JobFull extends JobSummary {
  skills: { skill: string | null; name: string; requirement: string; weight: number }[];
  sources: [string, string][];
  description: string;
  education_required: string | null;
  visa_requirement: string | null;
}

export interface Knockout {
  code: string;
  reason: string;
}

export interface SkillRef {
  skill: string;
  name: string;
  requirement: string;
  reason?: string;
}

export interface Component {
  points: number;
  max: number;
  ratio: number;
  explanation: string;
  detail?: Record<string, unknown>;
}

export interface SkillEvidence {
  name: string;
  requirement: string;
  credit: number;
  basis: string;
  fact_ids: string[];
  github: { repo: string; url: string }[];
}

export interface Match {
  match_id: string;
  job: JobSummary;
  label: string;
  estimated_fit_score: number;
  confidence: "high" | "medium" | "low";
  disclaimer: string;
  recommendation: string | null;
  knockouts: Knockout[];
  is_new: boolean;
  dismissed: boolean;
  why_matched: string[];
  why_not_matched: string[];
  missing_skills: SkillRef[];
  partial_skills: SkillRef[];
  risks: string[];
}

export interface MatchFull extends Omit<Match, "job"> {
  job: JobFull;
  components: Record<string, Component>;
  confidence_points: number;
  weights: Record<string, number>;
  profile: { tech_years: number; tech_years_source: string; level: number };
  previous_score: number | null;
  evidence: Record<string, SkillEvidence>;
  settings_version: number;
  job_content_version: number;
  threshold: number;
}

export interface MatchList {
  label: string;
  disclaimer: string;
  threshold: number;
  total: number;
  matches: Match[];
}

export interface Fact {
  id: string;
  fact_type: string;
  fact_key: string;
  data: Record<string, unknown>;
  source_type: string;
  source_ref: { sources?: Record<string, unknown>[] };
  review_status: "pending" | "verified" | "rejected";
  confidence: string;
}

export interface AuditEntry {
  id: string;
  at: string;
  actor: string;
  actor_detail: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  reason: string | null;
}

export interface AgentRun {
  id: string;
  agent_name: string;
  status: string;
  input_summary: string;
  output: Record<string, unknown>;
  confidence: string | null;
  errors: { code: string; message: string }[];
  started_at: string;
  finished_at: string | null;
}
