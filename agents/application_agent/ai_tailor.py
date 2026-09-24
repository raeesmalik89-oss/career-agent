"""AI rewriting of a prepared application: resume summary and bullets, cover letter, "why this company" draft.

The deterministic package (package.py) decides WHAT goes in: which facts, bullets and projects, in which order.
The AI only rewrites HOW it reads, for one job. It gets your career facts and the job text, never your contact
details. Every rewritten line keeps the fact IDs of the line it replaces and goes through the same validator as
everything else: a line that mentions a skill, tool or number the cited facts do not support is discarded and the
original wording is kept, with the reason reported. You still review and approve everything.
"""

import json
import time
import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.application_agent.package import PLACEHOLDER_RX, _facts, _personal
from agents.application_agent.validator import validate_item
from agents.match_agent.profile import build_profile
from agents.taxonomy import get_taxonomy
from app.db.enums import Actor
from app.db.models import Application, ApplicationAnswer, Job, ProfileFact, ResumeVersion
from app.services import settings_service
from app.services.secrets import get_secret
from integrations.llm import PROVIDERS, LLMError, Provider, chat_json

MAX_JOB_CHARS = 8000
MAX_FACT_CHARS = 14000
MAX_LINE = 400
DROP_KEYS = {"sources", "conflicts", "evidence", "spans", "offsets", "raw", "source_text", "github", "confidence"}

SYSTEM = """You tailor one job seeker's resume to one job posting. Honesty rules are absolute.

RULES
1. Use ONLY information written in FACTS or in the unit you are rewriting. Never add a skill, tool, technology,
   platform, employer, job title, certification, number, percentage, date or duration that is not written there.
   If the job asks for something the facts do not show, leave it out: do not imply it.
2. Rewrite each unit so a recruiter for THIS job sees its relevance: strong action verb first, the job's own
   vocabulary only where the fact supports it, outcome before detail. Keep the meaning. One sentence, at most 30
   words, no first person, no trailing full stop needed.
3. Training programmes, internships and courses stay described as training, never as paid employment.
4. "summary": 2-3 sentences, resume style (no "I"), from FACTS only, aimed at this role.
5. "cover_letter": exactly 3 short paragraphs, first person, no greeting and no sign-off: (a) the role and why the
   candidate's background fits, (b) the most relevant evidence from FACTS, (c) what they would bring. Plain,
   confident, not flowery.
6. "why_company": 1-2 first-person sentences on what in the JOB POSTING appeals to the candidate. Use only the
   posting's content; the candidate will edit it.

Return ONLY a JSON object:
{"summary": "...", "bullets": [{"id": "<unit id>", "text": "..."}], "cover_letter": ["...", "...", "..."],
 "why_company": "..."}
Include every unit id exactly once."""


class AiTailorError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def ai_config(db: Session, user_id: uuid.UUID) -> tuple[Provider | None, str | None, str | None, str]:
    """(provider or None if off, model, api key, ollama url)."""
    s = settings_service.get_effective(db, user_id)[0].ai
    if s.provider == "off":
        return None, None, None, s.ollama_url
    p = PROVIDERS[s.provider]
    return p, s.model or p.default_model, get_secret(db, user_id, p.secret) if p.secret else None, s.ollama_url


def _fact_brief(f: ProfileFact) -> dict | None:
    """What the AI may read about one fact. Personal/contact facts are never sent."""
    t = f.fact_type.value
    if t in ("personal", "preference"):
        return None
    data = {k: v for k, v in f.data.items() if k not in DROP_KEYS and v not in (None, "", [], {})}
    return {"id": str(f.id), "type": t, **data}


def _facts_payload(facts: list[ProfileFact]) -> list[dict]:
    out, size = [], 0
    order = {"experience": 0, "project": 1, "skill_claim": 2, "education": 3, "certification": 4}
    for f in sorted(facts, key=lambda f: order.get(f.fact_type.value, 9)):
        b = _fact_brief(f)
        if b is None:
            continue
        size += len(json.dumps(b, ensure_ascii=False))
        if size > MAX_FACT_CHARS:
            break
        out.append(b)
    return out


def _units(resume: dict) -> list[dict]:
    units = []
    for ei, e in enumerate(resume["experience"]):
        for bi, b in enumerate(e["bullets"]):
            units.append({"id": f"experience.{ei}.bullets.{bi}", "context": f"{e['title']} at {e['organization']}",
                          "text": b["text"]})  # fmt: skip
    for pi, p in enumerate(resume["projects"]):
        for bi, b in enumerate(p["bullets"]):
            units.append({"id": f"projects.{pi}.bullets.{bi}", "context": f"project {p['name']}", "text": b["text"]})
    return units


def _clean(text: object) -> str:
    s = " ".join(str(text or "").split())
    return s[:MAX_LINE].rstrip()


def _bullet(resume: dict, unit_id: str) -> dict:
    section, i, _, j = unit_id.split(".")
    return resume[section][int(i)]["bullets"][int(j)]


def tailor(
    db: Session,
    app: Application,
    *,
    chat: Callable[..., tuple[dict, dict]] | None = None,
) -> dict:
    """Rewrite the application's resume and letter with the configured AI. Returns a report of what changed."""
    from agents.application_agent.service import COVER_LETTER_Q, PRE_SUBMIT, _event, revalidate, store_resume

    if app.status not in PRE_SUBMIT:
        raise AiTailorError(409, "this application is already approved; withdraw or rebuild it first")
    provider, model, key, ollama_url = ai_config(db, app.user_id)
    if provider is None:
        raise AiTailorError(409, "AI is turned off. Choose a free provider in Settings → AI.")
    rv = db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
    job = db.get(Job, app.job_id)
    if rv is None or job is None:
        raise AiTailorError(409, "this application has no prepared resume yet; use Rebuild from facts first")

    resume = json.loads(json.dumps(rv.parsed["resume"]))  # a copy: the stored version stays intact on failure
    facts = _facts(db, app.user_id)
    by_id = {str(f.id): f for f in facts}
    taxonomy = get_taxonomy()
    settings, _ = settings_service.get_effective(db, app.user_id)
    profile = build_profile(db, app.user_id, taxonomy, settings)
    units = _units(resume)
    request = {
        "job": {"title": job.title, "company": job.company, "text": (job.description or "")[:MAX_JOB_CHARS]},
        "facts": _facts_payload(facts),
        "units": units,
    }

    chat = chat or chat_json  # looked up at call time so tests can substitute a fake provider
    started = time.monotonic()
    try:
        out, usage = chat(provider, model=model, api_key=key, ollama_url=ollama_url, system=SYSTEM,
                          user=json.dumps(request, ensure_ascii=False))  # fmt: skip
    except LLMError as exc:
        raise AiTailorError(502, str(exc)) from None
    seconds = round(time.monotonic() - started, 1)
    model = usage.get("model") or model  # the provider may have retired the configured model (see chat_json)

    cited_all = sorted({fid for sec in ("experience", "projects", "education", "certifications")
                        for e in resume[sec] for fid in e["fact_ids"]})  # fmt: skip

    def check(text: str, fact_ids: list[str], derived: list[str] | None = None) -> list[str] | None:
        """None if acceptable, else the validator's reasons."""
        v = validate_item({"text": text, "fact_ids": fact_ids, "derived": derived or []}, by_id, profile, taxonomy)
        return v.notes if v.status == "unsupported" else None

    kept: list[dict] = []
    accepted = 0
    ai_bullets = {str(b.get("id")): _clean(b.get("text")) for b in out.get("bullets", []) if isinstance(b, dict)}
    for u in units:
        new = ai_bullets.get(u["id"])
        if not new:
            kept.append({"part": u["id"], "reason": ["the AI did not rewrite this line"]})
            continue
        b = _bullet(resume, u["id"])
        reasons = check(new, b["fact_ids"], b.get("derived"))
        if reasons or PLACEHOLDER_RX.search(new):
            kept.append({"part": u["id"], "ai_text": new, "reason": reasons or ["contains a placeholder"]})
            continue
        if new != b["text"]:
            b.update(text=new, ai=True, original=b["text"])
            accepted += 1

    summary = _clean(out.get("summary"))
    if summary:
        reasons = check(summary, cited_all)
        if reasons:
            kept.append({"part": "summary", "ai_text": summary, "reason": reasons})
        else:
            original = (resume.get("summary") or {}).get("text")
            resume["summary"] = {"text": summary, "fact_ids": cited_all, "source": "AI, from your facts", "ai": True,
                                 "original": original}  # fmt: skip
            accepted += 1

    paragraphs = []
    for i, para in enumerate(out.get("cover_letter") or []):
        p = _clean(para).replace(" [", " (").replace("]", ")")
        if not p:
            continue
        reasons = check(p, cited_all)
        if reasons:
            kept.append({"part": f"cover letter paragraph {i + 1}", "ai_text": p, "reason": reasons})
        else:
            paragraphs.append(p)
    why = _clean(out.get("why_company"))
    why_ok = bool(why) and not check(why, cited_all) and not PLACEHOLDER_RX.search(why)
    if why and not why_ok:
        kept.append({"part": "why this company", "ai_text": why, "reason": check(why, cited_all) or ["placeholder"]})

    report = {
        "provider": provider.key,
        "model": model,
        "seconds": seconds,
        "lines_rewritten": accepted,
        "kept_original": kept,
        "tokens": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens") if k in usage},
    }
    store_resume(db, app, job, resume, ai=report)

    answers = {
        a.question: a for a in db.scalars(select(ApplicationAnswer).where(ApplicationAnswer.application_id == app.id))
    }
    meta = dict(app.policy_decision.get("answers_meta", {}))
    letter = answers.get(COVER_LETTER_Q)
    if letter is not None and paragraphs:
        personal = _personal(facts)
        contact = [personal[k] for k in ("name", "email", "phone") if k in personal]
        why_text = why if why_ok else f"[Why {job.company}: write one or two sentences in your own words.]"
        body = [f"Dear {job.company} hiring team,", *paragraphs, why_text, "Thank you for considering my application."]
        if contact:
            body.append("\n".join(str(v) for v, _ in contact))
        letter.answer = "\n\n".join(body)
        letter.cited_fact_ids = sorted(set(cited_all) | {fid for _, fid in contact})
        meta[str(letter.id)] = {"derived": [], "user_written": False, "ai": True}
    why_q = next((a for q, a in answers.items() if q.startswith("Why do you want to work at")), None)
    if why_q is not None and why_ok:
        why_q.answer = why
        why_q.cited_fact_ids = cited_all
        meta[str(why_q.id)] = {"derived": [], "user_written": False, "ai": True}
    app.policy_decision = {**app.policy_decision, "answers_meta": meta, "ai": report}
    _event(db, app, "ai_tailored", Actor.agent, provider=provider.key, model=model,
           rewritten=accepted, kept_original=len(kept))  # fmt: skip
    revalidate(db, app)
    return report
