"""Policy engine for applications (docs/ARCHITECTURE.md section 6). Every decision returns its full rule trace.

The rules mirror the approved YAML (prepare / require_approval / auto_submit). They are plain Python so each rule
is testable, and POLICY_VERSION is stored with every decision.
"""

from dataclasses import dataclass, field

from app.schemas.settings import UserSettings

POLICY_VERSION = "2026-09-24.1"
SENSITIVE = {"open_ended", "legal", "compensation", "relocation", "visa", "demographic"}


@dataclass
class Decision:
    outcome: str
    trace: list[dict] = field(default_factory=list)

    def rule(self, name: str, passed: bool, detail: str) -> bool:
        self.trace.append({"rule": name, "passed": passed, "detail": detail})
        return passed

    def dump(self) -> dict:
        return {"outcome": self.outcome, "policy_version": POLICY_VERSION, "trace": self.trace}


def decide_prepare(*, score: float, knockouts: list[dict], settings: UserSettings, requested_by_user: bool) -> Decision:
    """Automatic preparation needs score >= threshold and no knockout. The user may still ask for any job;
    that is recorded rather than hidden."""
    d = Decision("prepare")
    ok_score = d.rule(
        "score_at_or_above_threshold",
        score >= settings.preferences.min_fit_score,
        f"{score:g} vs threshold {settings.preferences.min_fit_score}",
    )
    ok_ko = d.rule("no_knockouts", not knockouts, "; ".join(k["reason"] for k in knockouts) if knockouts else "none")
    if not (ok_score and ok_ko):
        if requested_by_user:
            d.rule("requested_by_user", True, "you asked to prepare this application despite the rules above")
        else:
            d.outcome = "skip"
    return d


def decide_submission(
    *,
    settings: UserSettings,
    source_auto_apply_allowed: bool,
    answers: list[dict],
    resume_counts: dict,
    match_confidence: str | None,
    pk_eligibility: str,
    auto_submits_today: int,
) -> Decision:
    """Returns outcome 'pending_approval' (default) or 'auto_submit'. Never auto-submits anything sensitive,
    unsupported, unverified or on a source whose terms do not allow it."""
    d = Decision("pending_approval")
    prefs = settings.preferences
    unsupported = resume_counts.get("unsupported", 0) + sum(a["validation_status"] == "unsupported" for a in answers)
    needs = resume_counts.get("needs_approval", 0) + sum(a["validation_status"] == "needs_approval" for a in answers)
    sensitive = sorted({a["category"] for a in answers if a["category"] in SENSITIVE and not a.get("approved")})

    checks = [
        d.rule("auto_apply_enabled", prefs.auto_apply, f"Settings auto_apply = {prefs.auto_apply}"),
        d.rule(
            "approval_mode_allows_auto",
            prefs.approval_mode.value in ("AUTO", "HYBRID"),
            f"approval mode {prefs.approval_mode.value}",
        ),
        d.rule(
            "source_allows_automation",
            source_auto_apply_allowed,
            "source terms allow automated applying" if source_auto_apply_allowed else "source is assisted-only",
        ),
        d.rule("no_unsupported_claims", unsupported == 0, f"{unsupported} unsupported item(s)"),
        d.rule("nothing_needs_review", needs == 0, f"{needs} item(s) need your review"),
        d.rule("no_sensitive_questions", not sensitive, ", ".join(sensitive) or "none"),
        d.rule("confidence_not_low", match_confidence != "low", f"score confidence {match_confidence}"),
        d.rule("pakistan_eligibility_known", pk_eligibility != "unknown", f"eligibility {pk_eligibility}"),
        d.rule(
            "daily_auto_submit_limit",
            auto_submits_today < prefs.max_auto_submits_per_day,
            f"{auto_submits_today} of {prefs.max_auto_submits_per_day} today",
        ),
    ]
    if all(checks):
        d.outcome = "auto_submit"
    return d
