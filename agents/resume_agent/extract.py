"""Deterministic extraction of structured facts from sectioned resume lines.

Nothing here guesses: when a field cannot be found it is left as None and the analysis reports
"Evidence not found". Each extracted item keeps the lines it came from (for source_ref spans).
"""

import re
from dataclasses import dataclass, field
from datetime import date

from agents.resume_agent.parsing import Line
from agents.resume_agent.sections import Section, heading_name
from agents.taxonomy import Taxonomy

BULLETS = ("•", "●", "▪", "◦", "‣", "▸", "►", "➤", "✓", "✔", "-", "*", "–")
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}  # fmt: skip
_MONTH_RX = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE_RX = rf"(?:{_MONTH_RX}\s+)?(?:19|20)\d{{2}}"
RANGE_RX = re.compile(
    rf"(?P<start>{_DATE_RX})\s*(?:–|—|-|to|until)\s*(?P<end>{_DATE_RX}|present|current|now|ongoing)", re.I
)
SINGLE_DATE_RX = re.compile(rf"\(?(?P<d>{_DATE_RX})\)?", re.I)
EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RX = re.compile(r"\+?\d[\d\s().-]{8,}\d")
LINKEDIN_RX = re.compile(r"(?:https?://)?(?:www\.)?(?:linkedin\.com/)?in/[A-Za-z0-9_-]+", re.I)
GITHUB_RX = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9_-]+", re.I)
URL_RX = re.compile(r"https?://[^\s|,]+", re.I)
METRIC_RX = re.compile(
    r"(?:\b\d[\d,.]*\s?(?:%|x\b|ms\b|s\b|sec\b|seconds\b|min\b|hours?\b|k\b|m\b)|<\s?\d[\d.]*\s?\w+"
    r"|\b\d{1,3}(?:,\d{3})+\b|\b\d{2,}\+?\s+(?:patients|records|users|services|servers|nodes|pipelines|"
    r"partitions|features|clusters|requests|sites|staff|interns|models|tests))",
    re.I,
)
DEGREE_RX = re.compile(
    r"\b(?:diploma|degree|bachelor|master|doctor of|ph\.?d|pharm-?d|b\.?sc|m\.?sc|bs|ms|ba|ma|mba|bba|"
    r"b\.?e|b\.?tech|m\.?tech|hsc|ssc|f\.?sc|matric|intermediate|a-levels?|o-levels?|level \d)\b",
    re.I,
)
INSTITUTION_RX = re.compile(r"\b(?:university|college|institute|school|academy|polytechnic|numl)\b", re.I)
GRADE_RX = re.compile(r"(?:grade|cgpa|gpa|score|marks)\s*:?\s*(?P<g>[\d.]+\s*%?(?:\s*/\s*[\d.]+)?)", re.I)
TRAINING_RX = re.compile(r"\b(?:trainee|intern|internship|training program(?:me)?|apprentice)\b", re.I)
HEALTH_RX = re.compile(r"pharmac|hospital|clinical|patient|medical|health|drug|nurs|physician|\bmdr-tb\b", re.I)
TECH_RX = re.compile(
    r"engineer|devops|developer|aiops|mlops|cloud|\bsre\b|software|data|\bit\b|sysadmin|administrator|"
    r"platform|security analyst|machine learning",
    re.I,
)


def is_bullet(text: str) -> bool:
    return text.startswith(BULLETS) and (len(text) > 1 and text[1] in " \t" or text[0] in "•●▪◦‣▸►➤✓✔")


def strip_bullet(text: str) -> str:
    return text.lstrip("".join(BULLETS)).strip() if is_bullet(text) else text


def parse_date(s: str) -> str | None:
    """'Aug 2024' -> '2024-08', '2020' -> '2020', 'present' -> 'present'."""
    s = s.strip().lower().rstrip(".")
    if s in ("present", "current", "now", "ongoing"):
        return "present"
    m = re.match(rf"(?:(?P<mon>{_MONTH_RX})\s+)?(?P<y>(?:19|20)\d{{2}})", s, re.I)
    if not m:
        return None
    if m.group("mon"):
        return f"{m.group('y')}-{_MONTHS[m.group('mon')[:3].lower()]:02d}"
    return m.group("y")


def months_between(start: str | None, end: str | None, today: date | None = None) -> int | None:
    if not start:
        return None
    today = today or date.today()

    def ym(s: str, is_end: bool) -> tuple[int, int]:
        if s == "present":
            return today.year, today.month
        if "-" in s:
            y, m = s.split("-")
            return int(y), int(m)
        return int(s), 12 if is_end else 1

    if end is None:
        return None
    sy, sm = ym(start, False)
    ey, em = ym(end, True)
    if len(start) == 4 and end != "present" and len(end) == 4:
        return max(0, (ey - sy) * 12)  # year-only ranges: count whole years, e.g. 2020-2024 = 48
    return max(0, (ey - sy) * 12 + (em - sm) + 1)


# ------------------------------------------------------------------ data classes


@dataclass
class Extracted:
    kind: str
    data: dict
    lines: list[Line]
    confidence: str = "medium"


@dataclass
class Block:
    header: list[Line] = field(default_factory=list)
    bullets: list[list[Line]] = field(default_factory=list)  # each bullet may span wrapped lines

    @property
    def all_lines(self) -> list[Line]:
        return self.header + [ln for b in self.bullets for ln in b]

    def bullet_texts(self) -> list[str]:
        return [" ".join(strip_bullet(ln.text) if i == 0 else ln.text for i, ln in enumerate(b)) for b in self.bullets]


def _looks_like_tech_line(text: str) -> bool:
    return not is_bullet(text) and text.count("•") >= 2


def _is_wrapped_bullet_line(prev: str, text: str, nxt: str, wrap_width: int) -> bool:
    """Is `text` (a non-bullet line after a bullet) the wrapped tail of that bullet, or a new entry header?"""
    if text[:1].islower() or text[:1].isdigit() or text[:1] in "(&,;/":
        return True
    if RANGE_RX.search(text) or "|" in text or _looks_like_tech_line(text):
        return False  # dates, "Org | dates" and "Tech • Tech" lines are headers
    if RANGE_RX.search(nxt):
        return False  # a title line directly above "Org | Aug 2024 - Aug 2025"
    if prev.rstrip().endswith((".", "!", "?", ")", ";")):
        return False
    if re.search(r"(?:&|,|-|/|(?:and|or|with|of|to|for|via|in|on|the|a|an))\s*$", prev, re.I):
        return True  # previous line ends mid-phrase
    if is_bullet(nxt) and _looks_like_title(text):
        return False  # "Python Automation - Selenium + Jira" followed by its bullets
    # Text only wraps when the previous line was (nearly) full width.
    return len(prev) >= 0.75 * wrap_width


def _looks_like_title(text: str) -> bool:
    words = [w for w in re.findall(r"[A-Za-z][\w'.-]*", text)]
    caps = [w for w in words if w[0].isupper()]
    return 2 <= len(words) <= 9 and len(caps) >= 0.6 * len(words) and not text.rstrip().endswith(".")


def split_blocks(lines: list[Line]) -> list[Block]:
    """Group a section into entries: header lines followed by (possibly wrapped) bullets."""
    blocks: list[Block] = []
    cur: Block | None = None
    wrap_width = max((len(ln.text) for ln in lines), default=0)
    for i, ln in enumerate(lines):
        text = ln.text
        nxt = lines[i + 1].text if i + 1 < len(lines) else ""
        if is_bullet(text):
            if cur is None:
                cur = Block()
                blocks.append(cur)
            cur.bullets.append([ln])
            continue
        if cur is not None and cur.bullets:
            if _is_wrapped_bullet_line(cur.bullets[-1][-1].text, text, nxt, wrap_width):
                cur.bullets[-1].append(ln)
            else:
                cur = Block(header=[ln])
                blocks.append(cur)
            continue
        if cur is None:
            cur = Block()
            blocks.append(cur)
        cur.header.append(ln)
    return [b for b in blocks if b.header or b.bullets]


def _split_header(block: Block) -> tuple[list[str], str | None, str | None]:
    """Return (pieces without dates, start, end)."""
    start = end = None
    pieces: list[str] = []
    for ln in block.header:
        text = ln.text
        m = RANGE_RX.search(text)
        if m and start is None:
            start, end = parse_date(m.group("start")), parse_date(m.group("end"))
            text = (text[: m.start()] + text[m.end() :]).strip()
        for p in re.split(r"\s*\|\s*|\s+—\s+", text):
            p = p.strip(" –—-,")
            if p:
                pieces.append(p)
    return pieces, start, end


# ------------------------------------------------------------------ extractors


def extract_personal(sections: list[Section], all_lines: list[Line]) -> list[Extracted]:
    out: list[Extracted] = []
    head = [ln for s in sections if s.name in ("header", "contact") for ln in s.lines] or all_lines[:8]

    def first(rx: re.Pattern, lines: list[Line]) -> tuple[str, Line] | None:
        for ln in lines:
            m = rx.search(ln.text)
            if m:
                return m.group(0), ln
        return None

    # Name: a 2-4 word alphabetic line in the header/contact area, or right before a CONTACT heading.
    name_candidates = list(head)
    for s in sections:
        if s.name == "contact":
            idx = all_lines.index(s.lines[0]) if s.lines else None
            if idx:
                name_candidates = all_lines[max(0, idx - 3) : idx] + name_candidates
    for ln in name_candidates:
        words = ln.text.split()
        if 2 <= len(words) <= 4 and all(re.fullmatch(r"[A-Za-z.'-]+", w) for w in words) and not heading_name(ln.text):
            name = " ".join(w.capitalize() if w.isupper() else w for w in words)
            out.append(Extracted("personal", {"field": "name", "value": name}, [ln], "high"))
            break

    for field_, rx in (("email", EMAIL_RX), ("linkedin", LINKEDIN_RX), ("github", GITHUB_RX)):
        hit = first(rx, head) or first(rx, all_lines)
        if hit:
            value = hit[0].lower() if field_ != "email" else hit[0]
            if field_ == "linkedin" and "linkedin.com" not in value:
                value = "linkedin.com/" + value
            out.append(Extracted("personal", {"field": field_, "value": value}, [hit[1]], "high"))
    hit = first(PHONE_RX, head)
    if hit:
        out.append(Extracted("personal", {"field": "phone", "value": hit[0].strip()}, [hit[1]], "high"))

    for ln in head:
        for seg in re.split(r"\s*[|•]\s*", ln.text):
            if re.fullmatch(r"[A-Z][A-Za-z .'-]+,\s*[A-Z][A-Za-z .'-]+", seg.strip()) and "@" not in seg:
                out.append(Extracted("personal", {"field": "location", "value": seg.strip()}, [ln], "high"))
                break
        else:
            continue
        break

    avail = [
        ln for s in sections if s.name in ("header", "availability") for ln in s.lines
        if re.search(r"available|remote|relocat|on-site|onsite|time-zone|timezone|full-time|immediate", ln.text, re.I)
        and not EMAIL_RX.search(ln.text)
    ]  # fmt: skip
    if avail:
        out.append(
            Extracted("preference", {"field": "availability", "value": "; ".join(ln.text for ln in avail)}, avail)
        )

    langs: list[tuple[str, str | None]] = []
    lang_lines: list[Line] = []
    for s in sections:
        for ln in s.lines:
            text = ln.text
            if s.name == "languages" or text.lower().startswith("languages:"):
                body = text.split(":", 1)[1] if text.lower().startswith("languages:") else text
                for part in re.split(r",|;", body):
                    m = re.match(r"\s*([A-Za-z]+)\s*(?:[-–(]\s*([A-Za-z ]+)\)?)?", part)
                    if m and m.group(1):
                        langs.append((m.group(1), (m.group(2) or "").strip() or None))
                lang_lines.append(ln)
    if langs:
        out.append(
            Extracted(
                "personal",
                {"field": "languages", "value": [{"language": lang, "level": lvl} for lang, lvl in langs]},
                lang_lines,
                "high",
            )
        )
    return out


def extract_summary(sections: list[Section]) -> str | None:
    for s in sections:
        if s.name == "summary" and s.lines:
            return " ".join(ln.text for ln in s.lines)
    return None


def classify_sector(text: str) -> str:
    if TECH_RX.search(text) and not HEALTH_RX.search(text):
        return "tech"
    if HEALTH_RX.search(text):
        return "healthcare"
    return "other"


def extract_experience(section: Section, taxonomy: Taxonomy) -> list[Extracted]:
    out: list[Extracted] = []
    for block in split_blocks(section.lines):
        pieces, start, end = _split_header(block)
        if not pieces and not block.bullets:
            continue
        title = pieces[0] if pieces else None
        org = pieces[1] if len(pieces) > 1 else None
        if len(pieces) == 1 and start is None:
            title, org = None, pieces[0]  # a lone undated header line is an employer, not a job title
        bullets = block.bullet_texts()
        header_text = " ".join(pieces)
        sector = classify_sector(header_text)
        if sector == "other" and bullets:
            sector = classify_sector(" ".join(bullets))
        techs = sorted({h.key for b in bullets for h in taxonomy.find(b)})
        data = {
            "title": title,
            "organization": org,
            "details": pieces[2:],
            "start": start,
            "end": end,
            "months": months_between(start, end),
            "is_training": bool(TRAINING_RX.search(header_text)),
            "sector": sector,
            "responsibilities": bullets,
            "technologies": techs,
        }
        conf = "high" if title and org and start else "medium" if (title or org) and start else "low"
        out.append(Extracted("experience", data, block.all_lines, conf))
    return out


def extract_projects(section: Section, taxonomy: Taxonomy) -> list[Extracted]:
    out: list[Extracted] = []
    for block in split_blocks(section.lines):
        header = [ln.text for ln in block.header]
        if not header:
            continue
        name = header[0]
        tech_lines = [t for t in header[1:] if _looks_like_tech_line(t) or t.lower().startswith(("tech", "stack"))]
        context = [t for t in header[1:] if t not in tech_lines]
        bullets = block.bullet_texts()
        techs = sorted(
            {h.key for t in [name, *tech_lines, *bullets] for h in taxonomy.find(t, in_skills_list=t in tech_lines)}
        )
        out.append(
            Extracted(
                "project",
                {"name": name, "context": context, "technologies": techs, "highlights": bullets},
                block.all_lines,
                "high" if bullets else "medium",
            )
        )
    return out


def extract_education(section: Section) -> list[Extracted]:
    out: list[Extracted] = []
    cur: Extracted | None = None
    for ln in section.lines:
        text = strip_bullet(ln.text)
        for part in re.split(r"\s+\|\s+|\s+—\s+", text):
            part = part.strip()
            if not part:
                continue
            grade = GRADE_RX.search(part)
            if DEGREE_RX.search(part) and not grade and not INSTITUTION_RX.match(part):
                qual = part
                d = RANGE_RX.search(qual) or SINGLE_DATE_RX.search(qual)
                when = None
                if d:
                    when = parse_date(d.group("end") if "end" in d.groupdict() else d.group("d"))
                    qual = (qual[: d.start()] + qual[d.end() :]).strip(" ,–-")
                institution = None
                segs = [s.strip() for s in re.split(r",\s*", qual)]
                for i, seg in enumerate(segs[1:], start=1):
                    if INSTITUTION_RX.search(seg) or (i == len(segs) - 1 and seg.isupper() and len(segs) > 2):
                        institution = ", ".join(segs[i:])
                        qual = ", ".join(segs[:i])
                        break
                cur = Extracted(
                    "education",
                    {"qualification": qual.strip(" –-"), "institution": institution, "date": when, "grade": None},
                    [ln],
                    "medium",
                )
                out.append(cur)
            elif cur is not None:
                bare = re.fullmatch(rf"(?:passed\s+)?({_DATE_RX})", part, re.I)
                if bare:
                    if cur.data["date"] is None:
                        cur.data["date"] = parse_date(bare.group(1))
                elif grade:
                    cur.data["grade"] = grade.group("g").replace(" ", "")
                elif cur.data["institution"] is None and (
                    INSTITUTION_RX.search(part) or (len(part) < 60 and ":" not in part)
                ):
                    inst = part
                    d = SINGLE_DATE_RX.search(inst)
                    if d and cur.data["date"] is None:
                        cur.data["date"] = parse_date(d.group("d"))
                        inst = (inst[: d.start()] + inst[d.end() :]).strip(" ,–-")
                    inst = re.sub(r"^passed\s*", "", inst, flags=re.I)
                    if inst and not re.fullmatch(r"passed", inst, re.I):
                        cur.data["institution"] = inst
                elif re.match(r"passed", part, re.I):
                    d = SINGLE_DATE_RX.search(part)
                    if d and cur.data["date"] is None:
                        cur.data["date"] = parse_date(d.group("d"))
                else:
                    cur.data.setdefault("details", []).append(part)
                if ln not in cur.lines:
                    cur.lines.append(ln)
    for e in out:
        e.confidence = "high" if e.data["institution"] and e.data["date"] else "medium"
    return out


def extract_certifications_section(section: Section) -> list[Extracted]:
    out = []
    for ln in section.lines:
        text = strip_bullet(ln.text)
        if len(text) < 4:
            continue
        d = SINGLE_DATE_RX.search(text)
        out.append(
            Extracted(
                "certification",
                {
                    "name": text,
                    "issuer": None,
                    "credential_id": None,
                    "issued": parse_date(d.group("d")) if d else None,
                },
                [ln],
                "medium",
            )
        )
    return out


def extract_achievements(items: list[Extracted]) -> list[Extracted]:
    """Bullets with measurable results, linked to the experience/project they came from."""
    out = []
    for item in items:
        context = item.data.get("title") or item.data.get("name")
        texts = item.data.get("responsibilities") or item.data.get("highlights") or []
        for t in texts:
            metrics = [m.group(0).strip() for m in METRIC_RX.finditer(t)]
            if metrics:
                out.append(
                    Extracted(
                        "achievement",
                        {"text": t, "metrics": metrics, "context": context, "context_kind": item.kind},
                        item.lines,
                        "medium",
                    )
                )
    return out
