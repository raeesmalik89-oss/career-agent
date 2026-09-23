from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROLE_FAMILIES = [
    "devops",
    "cloud",
    "sre",
    "aiops",
    "ai_engineer",
    "ai_platform",
    "mlops",
    "devsecops",
    "kubernetes",
    "platform",
    "cloud_ai_infra",
    "sre_ai",
]
SENIORITY_LEVELS = ["intern", "entry", "junior", "mid", "senior", "staff", "principal"]


class ApprovalMode(StrEnum):
    AUTO = "AUTO"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    HYBRID = "HYBRID"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Salary(Strict):
    min_monthly_pkr: int | None = Field(None, ge=0)
    min_annual_usd: int | None = Field(None, ge=0)


class Preferences(Strict):
    """Defaults derived from the owner's CV (Islamabad; 12-month AIOps/DevOps training; 4 yrs healthcare)."""

    cities: list[str] = ["Islamabad", "Rawalpindi"]
    accept_remote: bool = True
    accept_hybrid: bool = True
    remote_countries: list[str] = ["Worldwide", "Pakistan", "APAC", "EMEA", "Middle East", "GCC"]
    target_role_families: list[str] = Field(
        default_factory=lambda: ["devops", "sre", "aiops", "ai_engineer", "mlops", "cloud", "platform", "devsecops"]
    )
    target_seniority: list[str] = ["entry", "junior", "mid"]
    tech_experience_years: float = Field(1.0, ge=0, le=50)
    domain_experience: dict[str, float] = {"healthcare": 4.0}
    preferred_domains: list[str] = ["healthcare", "aiops", "cloud", "security"]
    min_fit_score: int = Field(80, ge=0, le=100)
    daily_min_jobs_scanned: int = Field(30, ge=1, le=1000)
    salary: Salary = Salary()
    needs_visa_sponsorship: bool = False
    willing_to_relocate: bool = False
    auto_apply: bool = False
    approval_mode: ApprovalMode = ApprovalMode.HYBRID
    max_auto_submits_per_day: int = Field(5, ge=0, le=50)

    @model_validator(mode="after")
    def _check(self):
        bad = set(self.target_role_families) - set(ROLE_FAMILIES)
        if bad:
            raise ValueError(f"unknown role families: {sorted(bad)}")
        bad = set(self.target_seniority) - set(SENIORITY_LEVELS)
        if bad:
            raise ValueError(f"unknown seniority levels: {sorted(bad)}")
        return self


class ScoringWeights(Strict):
    skills: float = 30
    experience: float = 20
    github_evidence: float = 15
    education_certs: float = 10
    role_seniority: float = 10
    location_remote: float = 10
    domain: float = 5

    @model_validator(mode="after")
    def _sum_100(self):
        total = sum(self.model_dump().values())
        if abs(total - 100) > 1e-6:
            raise ValueError(f"scoring weights must sum to 100 (got {total})")
        if any(v < 0 for v in self.model_dump().values()):
            raise ValueError("scoring weights must be non-negative")
        return self


class Policy(Strict):
    knockout_pk_eligibility_unknown: bool = False  # False = score 0.5 on location, force approval
    knockout_seniority_gap_levels: int = Field(2, ge=1, le=6)
    knockout_experience_multiple: float = Field(2.0, ge=1.0)
    approval_required_categories: list[str] = [
        "open_ended",
        "legal",
        "compensation",
        "relocation",
        "visa",
        "demographic",
    ]
    daily_llm_budget_usd: float = Field(3.0, ge=0)


class Schedules(Strict):
    timezone: str = "Asia/Karachi"
    morning_scan: str = "0 7 * * *"
    afternoon_analysis: str = "0 14 * * *"
    evening_prep: str = "0 20 * * *"
    weekly_sync: str = "0 10 * * 0"
    delta_scans_enabled: bool = False


class UserSettings(Strict):
    preferences: Preferences = Preferences()
    scoring_weights: ScoringWeights = ScoringWeights()
    policy: Policy = Policy()
    schedules: Schedules = Schedules()


class UserSettingsOut(UserSettings):
    version: int
