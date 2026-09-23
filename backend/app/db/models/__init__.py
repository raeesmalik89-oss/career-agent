"""Importing this package registers every table on Base.metadata (used by Alembic)."""

from app.db.models.applications import Application, ApplicationAnswer, ApplicationEvent
from app.db.models.github import GithubEvidence, GithubProfile, GithubRepository
from app.db.models.identity import AuthSession, Secret, SettingsVersion, User
from app.db.models.jobs import Job, JobMatch, JobRaw, JobSkill, JobSource, JobSourceLink
from app.db.models.learning import (
    ConceptMap,
    InterviewAnswer,
    InterviewQuestion,
    InterviewSession,
    KnowledgeEdge,
    LearningItem,
    SkillGap,
)
from app.db.models.ops import AgentRun, AuditLog, DailyReport, Notification
from app.db.models.profile import ProfileFact, ResumeProfile, ResumeVersion, Skill, UserSkill

__all__ = [
    "AgentRun",
    "Application",
    "ApplicationAnswer",
    "ApplicationEvent",
    "AuditLog",
    "AuthSession",
    "ConceptMap",
    "DailyReport",
    "GithubEvidence",
    "GithubProfile",
    "GithubRepository",
    "InterviewAnswer",
    "InterviewQuestion",
    "InterviewSession",
    "Job",
    "JobMatch",
    "JobRaw",
    "JobSkill",
    "JobSource",
    "JobSourceLink",
    "KnowledgeEdge",
    "LearningItem",
    "Notification",
    "ProfileFact",
    "ResumeProfile",
    "ResumeVersion",
    "Secret",
    "SettingsVersion",
    "Skill",
    "SkillGap",
    "User",
    "UserSkill",
]
