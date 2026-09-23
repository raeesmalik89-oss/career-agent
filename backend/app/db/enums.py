from enum import StrEnum


class Role(StrEnum):
    owner = "owner"
    viewer = "viewer"
    system = "system"


class Confidence(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class ResumeKind(StrEnum):
    source = "source"
    tailored = "tailored"
    certificate = "certificate"


class ReviewStatus(StrEnum):
    pending = "pending"
    verified = "verified"
    rejected = "rejected"


class FileFormat(StrEnum):
    pdf = "pdf"
    docx = "docx"
    txt = "txt"
    md = "md"


class FactType(StrEnum):
    education = "education"
    certification = "certification"
    experience = "experience"
    skill_claim = "skill_claim"
    achievement = "achievement"
    project = "project"
    personal = "personal"
    preference = "preference"
    approved_answer = "approved_answer"


class SourceType(StrEnum):
    resume = "resume"
    github = "github"
    linkedin = "linkedin"
    manual = "manual"


class SkillCategory(StrEnum):
    cloud = "cloud"
    devops = "devops"
    programming = "programming"
    ai_ml = "ai_ml"
    aiops = "aiops"
    security = "security"
    healthcare = "healthcare"
    data = "data"
    other = "other"


class SkillLevel(StrEnum):
    strong = "strong"
    working = "working"
    exposure = "exposure"


class EvidenceType(StrEnum):
    file = "file"
    config = "config"
    code = "code"
    ci = "ci"
    test = "test"
    docs = "docs"
    commit = "commit"


class SourceKind(StrEnum):
    api = "api"
    rss = "rss"
    ats_board = "ats_board"
    email_import = "email_import"
    manual = "manual"


class RemoteType(StrEnum):
    remote = "remote"
    hybrid = "hybrid"
    onsite = "onsite"
    unknown = "unknown"


class PkEligibility(StrEnum):
    eligible = "eligible"
    ineligible = "ineligible"
    unknown = "unknown"


class Requirement(StrEnum):
    required = "required"
    preferred = "preferred"


class ApplicationStatus(StrEnum):
    prepared = "prepared"
    pending_approval = "pending_approval"
    approved = "approved"
    awaiting_manual_submit = "awaiting_manual_submit"
    submitting = "submitting"
    applied = "applied"
    failed = "failed"
    interview = "interview"
    technical_interview = "technical_interview"
    hr_interview = "hr_interview"
    rejected = "rejected"
    offer = "offer"
    withdrawn = "withdrawn"


class ApplicationMode(StrEnum):
    auto = "auto"
    assisted = "assisted"
    manual = "manual"


class AnswerCategory(StrEnum):
    factual = "factual"
    open_ended = "open_ended"
    legal = "legal"
    compensation = "compensation"
    relocation = "relocation"
    visa = "visa"
    demographic = "demographic"


class ValidationStatus(StrEnum):
    valid = "valid"
    unsupported = "unsupported"
    needs_approval = "needs_approval"


class Actor(StrEnum):
    user = "user"
    agent = "agent"
    system = "system"


class GapStatus(StrEnum):
    have = "have"
    partial = "partial"
    missing = "missing"


class LearningKind(StrEnum):
    explanation = "explanation"
    cheatsheet = "cheatsheet"
    lab = "lab"
    mini_project = "mini_project"
    troubleshooting = "troubleshooting"
    commands = "commands"


class RunStatus(StrEnum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
