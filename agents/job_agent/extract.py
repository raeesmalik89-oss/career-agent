"""Deterministic job-description analysis.

Every inference keeps the text it was based on (`evidence`), so the UI can show *why* a job was classified
as remote-eligible, senior, etc. When the text does not say, the answer is "unknown" - never a guess.
"""

import re
from dataclasses import dataclass, field

from agents.taxonomy import Taxonomy
from integrations.sources.base import JobPosting

ROLE_RULES: list[tuple[str, str]] = [  # (regex on title, role family) - first match wins
    (r"\b(site reliability|sre)\b.*\b(ai|ml|llm)\b|\b(ai|ml)\b.*\b(site reliability|sre)\b", "sre_ai"),
    (r"\bdevsecops\b|\b(cloud|platform|infrastructure|container|kubernetes)\s+security\s+engineer", "devsecops"),
    (r"\bsite reliability\b|\bsre\b", "sre"),
    (r"\baiops\b", "aiops"),
    (r"\bmlops\b|\bml\s*ops\b|\bml(\s|-)platform\b|\bmachine learning (platform|infrastructure|ops)", "mlops"),
    (r"\bai (platform|infrastructure)\b|\bllm (platform|infrastructure|ops)\b|\bllmops\b", "ai_platform"),
    (r"\bkubernetes\b|\bk8s\b", "kubernetes"),
    (r"\bplatform engineer", "platform"),
    (r"\bdevops\b|\bbuild (and|&) release\b|\brelease engineer", "devops"),
    (r"\bcloud (engineer|architect|infrastructure|operations|ops|administrator|consultant)", "cloud"),
    (r"\binfrastructure engineer", "cloud"),
    (
        r"\b(ai|ml|llm|genai|gen ai|machine learning|applied ai) (engineer|developer|specialist)\b|\bai/ml\b",
        "ai_engineer",
    ),
]
SENIORITY_RULES: list[tuple[str, str]] = [
    (r"\b(intern|internship|trainee|apprentice)\b", "intern"),
    (r"\b(graduate|entry[- ]level|new grad)\b", "entry"),
    (r"\b(junior|jr\.?|associate)\b", "junior"),
    (r"\b(principal|distinguished)\b", "principal"),
    (r"\bstaff\b", "staff"),
    (r"\b(head of|director|vp|vice president)\b", "principal"),
    (r"\b(engineering manager|manager)\b", "manager"),
    (r"\b(senior|sr\.?|lead|expert)\b", "senior"),
    (r"\b(mid[- ]level|intermediate|ii)\b", "mid"),
]
REQUIRED_HEADINGS = re.compile(
    r"(requirements|qualifications|what you('ll)? (need|bring)|must[- ]have|you (have|bring|are)|"
    r"who you are|about you|skills|experience|what we('re)? look(ing)? for|minimum|basic)",
    re.I,
)
PREFERRED_HEADINGS = re.compile(r"(nice[- ]to[- ]have|preferred|bonus|plus|desirable|good to have|extra credit)", re.I)
OTHER_HEADINGS = re.compile(
    r"(benefits|perks|what we offer|about (us|the company)|compensation|why join|our values)", re.I
)
YEARS_RX = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*)?\+?\s*years?(?:'|’)?\s*(?:of\s+)?"
    r"(?:[\w/+#.-]+\s+){0,4}?(?:experience|exp\.?)",
    re.I,
)
SALARY_RX = re.compile(
    r"(?P<cur>\$|€|£|USD|EUR|GBP|PKR|Rs\.?)\s?(?P<a>\d[\d,.]*)\s*(?P<ak>[kK])?\s*(?:-|–|to)\s*"
    r"(?:\$|€|£|USD|EUR|GBP|PKR|Rs\.?)?\s?(?P<b>\d[\d,.]*)\s*(?P<bk>[kK])?",
    re.I,
)

ELIGIBLE_WORDS = re.compile(r"\b(worldwide|anywhere|global(ly)?|pakistan|south asia|asia|apac|asia[- ]pacific)\b", re.I)
LOCAL_CITIES = re.compile(r"\b(islamabad|rawalpindi)\b", re.I)
PK_PLACES = re.compile(
    r"\b(pakistan|karachi|lahore|faisalabad|multan|peshawar|quetta|sialkot|gujranwala|hyderabad|abbottabad|"
    r"islamabad|rawalpindi)\b",
    re.I,
)
RESTRICTION_RX = re.compile(
    r"((must|need to|required to|should) (be )?(currently )?(be )?(located|based|resid\w*|living) in|"
    r"(only|exclusively) (open|available) to (candidates|applicants|residents) (in|from|of)|"
    r"(legally )?(authori[sz]ed|eligible|permitted) to work in|"
    r"(u\.?s\.?|us|uk|eu) (citizens?|residents?|persons?) only|"
    r"(right|permission) to work in|green card|security clearance|clearance required)"
    r"[^.\n]{0,80}",
    re.I,
)
TIMEZONE_RX = re.compile(r"\b(gmt|utc)\s?([+-]\s?\d{1,2})(?:\s?(?:to|-|–)\s?(?:gmt|utc)?\s?([+-]\s?\d{1,2}))?", re.I)
VISA_YES = re.compile(
    r"(visa sponsorship (is )?(available|provided|offered)|we (can |will )?sponsor|relocation "
    r"(and visa )?(support|assistance|package))",
    re.I,
)
VISA_NO = re.compile(
    r"(no (visa )?sponsorship|(unable|not able|cannot|can't|do not|don't|will not) "
    r"(to )?(provide |offer )?(visa )?sponsor)",
    re.I,
)
DEGREE_RX = re.compile(r"[^.\n]*\b(bachelor'?s?|master'?s?|b\.?s\.?c?|m\.?s\.?c?|phd|degree)\b[^.\n]*", re.I)
PK_TZ = 5


@dataclass
class JobAnalysis:
    role_family: str | None
    seniority: str | None
    seniority_evidence: str | None
    remote_type: str
    remote_evidence: str | None
    pk_eligibility: str
    pk_eligibility_evidence: str
    experience_years: float | None
    experience_evidence: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    salary_text: str | None
    visa: str | None
    education: str | None
    skills: list[dict] = field(default_factory=list)  # {skill, raw, requirement, weight}
    clearance_required: bool = False


def classify_role(title: str) -> str | None:
    t = title.lower()
    for rx, family in ROLE_RULES:
        if re.search(rx, t):
            return family
    return None


def classify_seniority(title: str, hint: str | None, years: float | None) -> tuple[str | None, str | None]:
    for rx, level in SENIORITY_RULES:
        m = re.search(rx, title, re.I)
        if m:
            return level, f"title: '{m.group(0)}'"
    if hint:
        h = hint.lower()
        for word, level in (
            ("entry", "entry"),
            ("junior", "junior"),
            ("mid", "mid"),
            ("senior", "senior"),
            ("lead", "senior"),
            ("staff", "staff"),
            ("principal", "principal"),
        ):
            if word in h:
                return level, f"source seniority: '{hint}'"
    if years is not None:
        level = "entry" if years <= 1 else "junior" if years <= 2 else "mid" if years <= 4 else "senior"
        return level, f"{years:g}+ years required"
    return None, None


def split_sections(text: str) -> dict[str, str]:
    """Rough split of a description into required / preferred / other text by headings."""
    buckets = {"required": [], "preferred": [], "other": [], "general": []}
    current = "general"
    for line in text.splitlines():
        stripped = line.strip().strip(":#*").strip()
        short = len(stripped) <= 60 and not stripped.endswith(".")
        if short and PREFERRED_HEADINGS.search(stripped):
            current = "preferred"
        elif short and OTHER_HEADINGS.search(stripped):
            current = "other"
        elif short and REQUIRED_HEADINGS.search(stripped):
            current = "required"
        buckets[current].append(line)
    return {k: "\n".join(v) for k, v in buckets.items()}


def extract_years(text: str) -> tuple[float | None, str | None]:
    found = []
    for m in YEARS_RX.finditer(text):
        lo = int(m.group(1))
        if 0 < lo <= 20:
            found.append((lo, m.group(0).strip()))
    if not found:
        return None, None
    lo, quote = min(found)  # the smallest stated requirement is the minimum
    return float(lo), quote


def extract_salary(p: JobPosting) -> tuple[float | None, float | None, str | None, str | None]:
    if p.salary_min or p.salary_max:
        text = (
            p.salary_text
            or f"{p.salary_min or ''}-{p.salary_max or ''} {p.salary_currency or ''} {p.salary_period or ''}"
        )
        return p.salary_min, p.salary_max, p.salary_currency, text.strip()
    for source_text in filter(None, [p.salary_text, p.description]):
        m = SALARY_RX.search(source_text)
        if m:

            def num(v, k):
                n = float(v.replace(",", "").rstrip("."))
                return n * 1000 if k else n

            cur = {"$": "USD", "€": "EUR", "£": "GBP", "RS": "PKR", "RS.": "PKR"}.get(
                m.group("cur").upper(), m.group("cur").upper()
            )
            return num(m.group("a"), m.group("ak")), num(m.group("b"), m.group("bk")), cur, m.group(0).strip()
    return None, None, None, None


REMOTE_WORDS = [
    (r"\bhybrid\b(?! cloud)", "hybrid"),
    (
        r"\b(fully |100% |completely )?remote\b(?![- ](debug\w*|access|sensing|control|monitoring|patient|work ?shop))",
        "remote",
    ),
    (r"\bwork(ing)? from home\b|\bwfh\b", "remote"),
    (r"\bon[- ]?site\b|\bin[- ]office\b|\bin the office\b", "onsite"),
]


def remote_type(p: JobPosting) -> tuple[str, str | None]:
    if p.remote_hint:
        return p.remote_hint, f"source field: {p.remote_hint}"
    for text, where in ((f"{p.title}\n{p.location or ''}", "title/location"), (p.description, "description")):
        for rx, kind in REMOTE_WORDS:
            m = re.search(rx, text, re.I)
            if m:
                return kind, f"{where}: '{m.group(0)}'"
    if p.location and not re.search(r"remote|anywhere|worldwide", p.location, re.I):
        return "onsite", f"location only: '{p.location}'"
    return "unknown", None


def restrictions_from_location(location: str | None) -> list[str]:
    """'Remote, Canada; Remote, United States' -> ['Canada', 'United States']."""
    out = []
    for seg in re.split(r";|\||/|\bor\b", location or ""):
        seg = re.sub(r"\(?\b(remote|hq|headquarters|anywhere|work(ing)? from home|wfh)\b\)?", " ", seg, flags=re.I)
        seg = re.sub(r"^[\s,\-–:]+|[\s,\-–:]+$", "", seg)
        if seg:
            out.append(seg)
    return out


def pk_eligibility(p: JobPosting, remote: str) -> tuple[str, str]:
    """eligible / ineligible / unknown, with the quote that justifies it. Unknown is never shown as eligible."""
    loc_blob = " | ".join([p.location or "", *p.location_restrictions])
    if remote in ("onsite", "hybrid"):
        if LOCAL_CITIES.search(loc_blob):
            return "eligible", f"{remote} in '{p.location}'"
        if p.location and re.fullmatch(r"\s*pakistan\s*", p.location, re.I):
            return "unknown", f"{remote} in Pakistan, city not stated. Evidence not found."
        if p.location:
            return "ineligible", f"{remote} role located in '{p.location}'"
    place = PK_PLACES.search(loc_blob)
    if remote == "remote" and place:
        return "eligible", f"remote role based in Pakistan: '{place.group(0)}' (location: {p.location})"
    m = RESTRICTION_RX.search(p.description)
    restriction_quote = m.group(0).strip() if m else None
    if restriction_quote and not re.search(r"pakistan", restriction_quote, re.I):
        return "ineligible", f'description: "{restriction_quote}"'
    if p.location_restrictions:
        if any(ELIGIBLE_WORDS.search(r) for r in p.location_restrictions):
            hit = next(r for r in p.location_restrictions if ELIGIBLE_WORDS.search(r))
            return "eligible", f"location restriction includes '{hit}'"
        return "ineligible", f"restricted to: {', '.join(p.location_restrictions[:6])}"
    if p.location and ELIGIBLE_WORDS.search(p.location):
        return "eligible", f"location: '{p.location}'"
    listed = restrictions_from_location(p.location)
    if remote == "remote" and listed:
        # A remote role advertised for named places ("Remote, Canada") expects candidates there.
        return "ineligible", f"remote role listed for: {', '.join(listed[:6])}"
    tz = (p.raw or {}).get("timezoneRestrictions")
    if isinstance(tz, list) and tz:
        return (
            ("eligible", f"timezone restriction includes UTC+{PK_TZ}")
            if PK_TZ in tz
            else ("ineligible", f"timezone restriction {tz} excludes UTC+{PK_TZ}")
        )
    m = TIMEZONE_RX.search(p.description)
    if m:
        lo = int(m.group(2).replace(" ", ""))
        hi = int(m.group(3).replace(" ", "")) if m.group(3) else lo
        if lo - 3 <= PK_TZ <= hi + 3:
            return "eligible", f"description: '{m.group(0)}' is within 3h of Pakistan (UTC+5)"
    m = re.search(
        r"[^.\n]*\b(worldwide|anywhere in the world|work from anywhere|fully distributed)\b[^.\n]*", p.description, re.I
    )
    if m:
        return "eligible", f'description: "{m.group(0).strip()[:160]}"'
    return "unknown", "Evidence not found."


def extract_skills(p: JobPosting, taxonomy: Taxonomy) -> list[dict]:
    sections = split_sections(p.description)
    out: dict[str, dict] = {}

    def add(text: str, requirement: str, weight: float) -> None:
        for h in taxonomy.find(text):
            cur = out.get(h.key)
            if cur is None or weight > cur["weight"]:
                out[h.key] = {"skill": h.key, "raw": h.surface, "requirement": requirement, "weight": weight}

    add(sections["general"], "preferred", 0.5)  # mentioned without a heading: counts, but less
    add(sections["preferred"], "preferred", 0.5)
    add(sections["required"], "required", 1.0)
    add(p.title, "required", 1.0)
    for tag in p.tags:
        for h in taxonomy.find(tag, in_skills_list=True):
            out.setdefault(h.key, {"skill": h.key, "raw": h.surface, "requirement": "preferred", "weight": 0.5})
    # generic umbrella words are not skills a candidate can be matched on
    for generic in ("devops", "monitoring", "logging", "json", "yaml", "git"):
        if generic in out and out[generic]["requirement"] != "required":
            out.pop(generic)
    return sorted(out.values(), key=lambda s: (-s["weight"], s["skill"]))


def analyze(p: JobPosting, taxonomy: Taxonomy) -> JobAnalysis:
    sections = split_sections(p.description)
    years, years_quote = extract_years(sections["required"] or p.description)
    if years is None:
        years, years_quote = extract_years(p.description)
    seniority, sen_ev = classify_seniority(p.title, p.seniority_hint, years)
    remote, remote_ev = remote_type(p)
    elig, elig_ev = pk_eligibility(p, remote)
    smin, smax, scur, stext = extract_salary(p)
    visa = (
        "sponsorship available"
        if VISA_YES.search(p.description)
        else ("no sponsorship" if VISA_NO.search(p.description) else None)
    )
    edu = DEGREE_RX.search(sections["required"] or p.description)
    return JobAnalysis(
        role_family=classify_role(p.title),
        seniority=seniority,
        seniority_evidence=sen_ev,
        remote_type=remote,
        remote_evidence=remote_ev,
        pk_eligibility=elig,
        pk_eligibility_evidence=elig_ev,
        experience_years=years,
        experience_evidence=years_quote,
        salary_min=smin,
        salary_max=smax,
        salary_currency=scur,
        salary_text=stext,
        visa=visa,
        education=edu.group(0).strip()[:300] if edu else None,
        skills=extract_skills(p, taxonomy),
        clearance_required=bool(re.search(r"security clearance|clearance required|\bts/sci\b", p.description, re.I)),
    )
