"""AI suggestions for the answers only you can write: why this company, expected salary, other open questions.

The AI proposes up to 3 options; nothing is saved until you pick one (it lands in the editor) and press Save, and a
picked option then counts as your own words. Motivation options may use only the job posting and your facts: any
option that names a skill you have no evidence for, or a number that is neither in your facts nor in the posting,
is dropped. Salary options are estimates from the posting, the location and your experience level, never below
the minimum in your Settings; the AI's market knowledge can be out of date, so the page says so.

Suggestions are cached on the application per answer, so reopening the page costs no tokens.
"""

import json
import time
from collections.abc import Callable

from sqlalchemy.orm import Session

from agents.application_agent.ai_tailor import MAX_JOB_CHARS, _clean, _facts_payload, ai_config
from agents.application_agent.package import PLACEHOLDER_RX, _facts
from agents.application_agent.validator import NUMBER_RX, validate_item
from agents.match_agent.profile import build_profile
from agents.taxonomy import get_taxonomy
from app.db.models import Application, ApplicationAnswer, Job
from app.services import settings_service
from integrations.llm import LLMError, chat_json

MAX_OPTIONS = 3
ASK_FOR = {"salary": 3, "motivation": 5, "generic": 4}  # spares: options the validator rejects are dropped
MAX_OUTPUT_TOKENS = 900
MAX_FACT_CHARS = 3500  # smaller than a full rewrite: a suggestion needs the gist, not every fact
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["options"],
    "properties": {
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "why"],
                "properties": {"text": {"type": "string"}, "why": {"type": "string"}},
            },
        }
    },
}

COMMON = """You suggest answers for one job seeker's application form. They will pick one option and may edit it.
Give exactly {n} options that differ in angle, not just in wording. For each: "text" is the answer exactly as it
would be pasted into the form, and "why" is at most 12 words telling the candidate what the option leans on.
Plain language, no buzzword stacking, no exclamation marks, no placeholders or [brackets]."""

MOTIVATION = (
    COMMON
    + """

The question asks why the candidate wants this job at this company. Each "text" is 1-2 first-person sentences.
RULES: take what appeals about the company or role ONLY from JOB POSTING, and connect it to something written in
CANDIDATE. The only technologies the candidate may name are those in CANDIDATE.skills_with_evidence: if the
posting asks for others (e.g. LLMs, GenAI, RAG), do not name them, not even as something to learn; say "this
work" or "the role" instead. Never add an employer, number or achievement that is not written in CANDIDATE.
Training stays described as training. If the posting says little about the company, focus on the role.
Angles to spread over: the company's product, customers or growth; the role's work matching the candidate's
evidence; learning and growth the posting offers; the team or way of working the posting describes."""
)

SALARY = (
    COMMON
    + """

The question asks for the candidate's expected salary. Each "text" is a short answer, for example
"PKR 120,000 - 150,000 per month (negotiable)". Use the currency and pay period of the posting or its location
(PKR per month for jobs in Pakistan; for remote jobs abroad, the employer's currency). If the posting states a
salary, stay inside it. Price the CANDIDATE's level for this kind of role, not the job title: someone with about
a year of hands-on training is hired at junior level even when applying to a senior post. Larger and
foreign-owned employers pay towards the top of a band. Never go below CANDIDATE.minimum when it is set; if
CANDIDATE.current_answer is set, treat it as the candidate's own figure and keep one option close to it.

Reference bands, gross PKR per month, Pakistani tech companies (Islamabad, Lahore, Karachi), 2025-26, approximate:
  trainee or intern 40,000-90,000 | junior, 0-2 years 100,000-220,000 | mid, 2-5 years 220,000-450,000 |
  senior, 5+ years 450,000-900,000. DevOps, cloud and ML roles sit in the upper half of each band.
Remote roles for foreign employers usually pay 1.5-3x the local band, quoted in USD per month or year.

Options: (1) safe, lower end of the realistic band, (2) the middle, (3) ambitious but defensible. Round figures,
give a range for the first two. Each "why" names the basis (e.g. "junior DevOps band, large employer")."""
)

GENERIC = (
    COMMON
    + """

Answer the QUESTION for this job. Each "text" is as long as the question needs (one short sentence for a simple
question, at most 4 sentences for an open one), first person. Use ONLY what is written in CANDIDATE and JOB
POSTING; never add an employer, number or achievement, and only name technologies listed in
CANDIDATE.skills_with_evidence."""
)


class SuggestError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def kind_of(answer: ApplicationAnswer) -> str | None:
    """Which kind of help an answer can get, or None if it is plain data from your facts (name, email...)."""
    from agents.application_agent.service import COVER_LETTER_Q

    cat = answer.category.value
    has_gap = not answer.answer.strip() or bool(PLACEHOLDER_RX.search(answer.answer))
    if cat == "compensation":
        return "salary"
    if answer.question.startswith("Why do you want to work at"):
        return "motivation"
    if answer.question == COVER_LETTER_Q:
        return "motivation" if has_gap else None  # fills the [Why …] sentence, not the whole letter
    if cat == "open_ended" or has_gap:
        return "generic"
    return None


def _numbers(text: str) -> list[str]:
    return [n.replace(",", "").rstrip("%") for n in NUMBER_RX.findall(text or "")]


def suggest(
    db: Session,
    app: Application,
    answer: ApplicationAnswer,
    *,
    refresh: bool = False,
    chat: Callable[..., tuple[dict, dict]] | None = None,
) -> dict:
    """2-3 suggested answers for one question. Cached per answer unless `refresh`."""
    kind = kind_of(answer)
    if kind is None:
        raise SuggestError(400, "this answer comes from your facts; edit it directly")
    cache = dict(app.policy_decision.get("suggestions", {}))
    if not refresh and str(answer.id) in cache:
        return cache[str(answer.id)] | {"cached": True}

    provider, model, key, ollama_url = ai_config(db, app.user_id)
    if provider is None:
        raise SuggestError(409, "AI is turned off. Choose a free provider in Settings → AI.")
    job = db.get(Job, app.job_id)
    facts = _facts(db, app.user_id)
    by_id = {str(f.id): f for f in facts}
    taxonomy = get_taxonomy()
    settings, _ = settings_service.get_effective(db, app.user_id)
    profile = build_profile(db, app.user_id, taxonomy, settings)
    skills = sorted(s.name for s in profile.skills.values() if s.level in ("strong", "working"))
    job_text = (job.description or "")[:MAX_JOB_CHARS]

    candidate: dict = {
        "technology_experience": f"{profile.tech_years:g} years"
        + (" (all of it a hands-on training programme, not paid employment)" if profile.training_only else ""),
        "skills_with_evidence": skills,
    }
    if kind == "salary":
        sal = settings.preferences.salary
        candidate["minimum"] = {k: v for k, v in (("monthly_pkr", sal.min_monthly_pkr),
                                                  ("annual_usd", sal.min_annual_usd)) if v} or None  # fmt: skip
        candidate["based_in"] = ", ".join(settings.preferences.cities) or None
        other = [f for f in _facts_payload(facts, [])["items"] if f["type"] in ("experience", "education")]
        candidate["background"] = [{k: v for k, v in f.items() if k != "id"} for f in other]
        if answer.answer.strip() and not PLACEHOLDER_RX.search(answer.answer):
            candidate["current_answer"] = answer.answer.strip()[:200]
    else:
        payload = _facts_payload(facts, skills)
        size, items = 0, []
        for it in payload["items"]:
            size += len(json.dumps(it, ensure_ascii=False))
            if size > MAX_FACT_CHARS:
                break
            items.append({k: v for k, v in it.items() if k != "id"})
        candidate["facts"] = items

    posting = {"title": job.title, "company": job.company, "location": job.location,
               "remote": job.remote_type.value, "seniority": job.seniority, "text": job_text}  # fmt: skip
    if job.salary_min or job.salary_max or job.salary_source_text:
        posting["salary_stated"] = {"min": float(job.salary_min) if job.salary_min else None,
                                    "max": float(job.salary_max) if job.salary_max else None,
                                    "currency": job.salary_currency, "text": job.salary_source_text}  # fmt: skip
    question = answer.question
    if kind == "motivation":
        question = f"Why do you want to work at {job.company}?"
    request = {"QUESTION": question, "JOB POSTING": posting, "CANDIDATE": candidate}
    system = {"salary": SALARY, "motivation": MOTIVATION}.get(kind, GENERIC).replace("{n}", str(ASK_FOR[kind]))

    chat = chat or chat_json
    started = time.monotonic()
    try:
        out, usage = chat(provider, model=model, api_key=key, ollama_url=ollama_url, system=system,
                          user=json.dumps(request, ensure_ascii=False), schema=SCHEMA, temperature=0.7,
                          max_tokens=MAX_OUTPUT_TOKENS)  # fmt: skip
    except LLMError as exc:
        raise SuggestError(502, str(exc)) from None

    cited_all = sorted(by_id)
    posting_numbers = _numbers(job_text) + _numbers(json.dumps(posting.get("salary_stated") or {}))
    options, dropped = [], []
    for o in out.get("options") or []:
        if not isinstance(o, dict):
            continue
        text = _clean(o.get("text")).replace("[", "(").replace("]", ")")
        why = _clean(o.get("why"))[:120]
        if not text or any(text == x["text"] for x in options):
            continue
        if kind != "salary":
            # the same checks as every generated line; numbers in the posting are allowed
            v = validate_item({"text": text, "fact_ids": cited_all, "derived": posting_numbers}, by_id, profile,
                              taxonomy)  # fmt: skip
            if v.status == "unsupported":
                dropped.append({"text": text, "reason": v.notes})
                continue
        options.append({"text": text, "why": why})
        if len(options) == MAX_OPTIONS:
            break
    if not options:
        raise SuggestError(502, "the AI's suggestions all named things your profile has no evidence for; "
                                "try again or write this one yourself")  # fmt: skip

    result = {
        "kind": kind,
        "options": options,
        "dropped": len(dropped),
        "note": "Estimates from the posting, the location and your experience. AI market knowledge can be out of "
        "date: compare with a salary site before you answer."
        if kind == "salary"
        else "Written from the job posting and your facts. Pick one, then make it sound like you.",
        "model": usage.get("model") or model,
        "seconds": round(time.monotonic() - started, 1),
        "fills": "placeholder" if PLACEHOLDER_RX.search(answer.answer) else "answer",
    }
    cache[str(answer.id)] = result
    app.policy_decision = {**app.policy_decision, "suggestions": cache}
    return result | {"cached": False}
