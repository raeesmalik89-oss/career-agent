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
  employer_url: string | null;
  aggregator_link: boolean;
  content_version: number;
  summary_only: boolean;
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

export interface ApplicationSummary {
  id: string;
  status: string;
  mode: string;
  job: { id: string; title: string; company: string; location: string | null };
  score: number | null;
  confidence: string | null;
  created_at: string;
  last_update: string;
  submitted_at: string | null;
}

export interface ResumeItem {
  text: string;
  fact_ids: string[];
}

export interface TailoredResume {
  header: Record<string, ResumeItem>;
  summary: { text: string } | null;
  skills: { group: string; items: (ResumeItem & { skill: string })[] }[];
  experience: { title: string; organization: string; dates: string; note: string | null; bullets: ResumeItem[]; conflicts: boolean }[];
  projects: { name: string; technologies: string[]; repo: string | null; bullets: ResumeItem[] }[];
  education: { qualification: string; institution: string; date: string; grade: string | null }[];
  certifications: { name: string; issuer: string | null; issued: string | null; credential_id: string | null }[];
}

export interface CheckItem {
  path: string;
  text: string;
  status: "valid" | "needs_approval" | "unsupported";
  notes: string[];
}

export interface PolicyTrace {
  outcome: string;
  policy_version: string;
  trace: { rule: string; passed: boolean; detail: string }[];
}

export interface ApplicationAnswerRow {
  id: string;
  question: string;
  answer: string;
  category: string;
  validation_status: "valid" | "needs_approval" | "unsupported";
  validation_notes: string[];
  cited_fact_ids: string[];
  approved: boolean;
}

export interface ApplicationDetail extends ApplicationSummary {
  application_url: string | null;
  resume: TailoredResume | null;
  resume_filename: string | null;
  resume_validation: { items: CheckItem[]; counts: Record<string, number> } | null;
  policy: { prepare: PolicyTrace | null; submission: PolicyTrace | null };
  blockers: string[];
  answers: ApplicationAnswerRow[];
  events: { type: string; actor: string; at: string; detail: Record<string, unknown> }[];
  next_statuses: string[];
}

export interface PackQuestion {
  id: string;
  bank_id: string | null;
  question: string;
  difficulty: string;
  tests: string;
  key_points: string[];
  model_answer: string;
  spoken_answer: string | null;
  common_mistakes: string[];
  follow_up: string;
}

export interface InterviewPack {
  date: string;
  total: number;
  sections: { key: string; title: string; questions: PackQuestion[] }[];
  disclaimer: string;
}

export interface NextQuestion {
  question_id: string;
  index: number;
  total: number;
  section: string;
  section_title: string;
  difficulty: string;
  question: string;
  tests: string;
}

export interface AnswerFeedback {
  question_id: string;
  question: string;
  your_answer?: string;
  score: number | null;
  rubric?: Record<string, { points: number; max: number; note: string }>;
  covered?: string[];
  missing_concepts?: string[];
  mistakes?: string[];
  common_mistakes?: string[];
  model_answer?: string;
  spoken_version?: string;
  follow_up?: string;
  disclaimer?: string;
  next?: NextQuestion | null;
}

export interface InterviewSessionDetail {
  id: string;
  mode: string;
  mode_title: string | null;
  started_at: string;
  ended_at: string | null;
  avg_score: number | null;
  answered: number;
  total: number;
  items: AnswerFeedback[];
  next: NextQuestion | null;
  disclaimer: string;
}

export interface InterviewStats {
  answers: number;
  sessions: number;
  average: number | null;
  by_section: Record<string, { title: string; answers: number; average: number }>;
  trend: { day: string; average: number }[];
  weakest: { question: string; section: string; last_score: number }[];
  disclaimer: string;
}

export interface SkillGapRow {
  skill: string;
  name: string;
  category: string;
  jobs_requiring: number;
  frequency_pct: number;
  required_pct: number;
  trend_7d: number | null;
  in_qualifying_jobs: number;
  have_level: string | null;
  status: "have" | "partial" | "missing";
  status_reason: string;
  role_importance: number;
  interview_importance: number;
  priority: number;
  families: string[];
  guide: boolean;
}

export interface GapReport {
  window_days: number;
  jobs_analysed: number;
  qualifying_jobs: number;
  weights: Record<string, number>;
  gaps: SkillGapRow[];
}

export interface LearningItemRow {
  id: string;
  skill: string;
  kind: string;
  title: string;
  content_md: string;
  status: "todo" | "in_progress" | "done";
  completed_at: string | null;
}

export interface EvidenceStatus {
  level: string | null;
  resume: string | null;
  github_repos: string[];
  note: string;
}

export interface MapNode {
  label: string;
  children: MapNode[];
}

export interface SkillGuide {
  guide: {
    key: string;
    title: string;
    curated: boolean;
    why: string;
    explanation: string;
    cheatsheet?: string[];
    commands?: { cmd: string; what: string }[];
    lab?: { goal: string; steps: string[]; done_when: string };
    troubleshooting?: { problem: string; fix: string }[];
    mini_project: { title: string; brief: string; steps: string[]; evidence: string };
    resources: { title: string; url: string }[];
  };
  evidence: EvidenceStatus;
  items: LearningItemRow[];
  concept_map: { tree: MapNode; mermaid: string; markdown: string } | null;
}

export interface LearningPlan {
  skills: { skill: string; name: string; done: number; total: number; items: LearningItemRow[]; evidence: EvidenceStatus }[];
}

export type RunStatus = "running" | "succeeded" | "partial" | "failed";

export interface PipelineStep {
  step: string;
  status: "succeeded" | "partial" | "failed" | "skipped";
  summary?: Record<string, unknown>;
  error?: string;
  note?: string;
  seconds?: number;
}

export interface PipelineRunRow {
  id: string;
  pipeline: string;
  title: string;
  trigger: "schedule" | "catch_up" | "manual";
  status: RunStatus;
  scheduled_for: string;
  started_at: string;
  finished_at: string | null;
  steps: PipelineStep[];
}

export interface PipelinesInfo {
  enabled: boolean;
  timezone: string;
  scheduler: { last_seen: string | null; running: boolean };
  pipelines: {
    name: string;
    title: string;
    about: string;
    steps: string[];
    cron: string | null;
    schedule: string;
    next_run: string | null;
    last_run: PipelineRunRow | null;
  }[];
}

export interface NotificationItem {
  id: string;
  kind: string;
  severity: "info" | "important" | "urgent";
  title: string;
  body: string | null;
  link: string | null;
  created_at: string;
  read_at: string | null;
  delivered: Record<string, { status: string | null; error: string | null }>;
}

export interface NotificationsOut {
  unread: number;
  items: NotificationItem[];
}

export interface DailyReportSummary {
  date: string;
  generated_at: string;
  headline: { new_jobs: number; qualifying_new: number; needs_you: number; answered: number };
}

export interface DailyReportDoc {
  date: string;
  generated_at: string;
  metrics: Record<string, unknown>;
  content_md: string;
}
