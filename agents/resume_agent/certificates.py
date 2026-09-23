"""Certificate documents and licence sections -> certification facts."""

import re

from agents.resume_agent.extract import Extracted, parse_date
from agents.resume_agent.parsing import ParsedDocument
from agents.resume_agent.sections import Section

_DATE_WORDS = r"\d{1,2}\s+[A-Za-z]+\s+(?:19|20)\d{2}|[A-Za-z]+\s+\d{1,2},?\s+(?:19|20)\d{2}|(?:19|20)\d{2}-\d{2}-\d{2}"


def looks_like_certificate(doc: ParsedDocument) -> bool:
    t = doc.text.lower()
    return (
        len(doc.lines) <= 40
        and "certificate" in t
        and any(k in t for k in ("awarded to", "certificate id", "has successfully completed", "this is to certify"))
    )


def _full_date(s: str) -> str | None:
    s = s.strip()
    m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+((?:19|20)\d{2})", s)
    if m:
        ym = parse_date(f"{m.group(2)} {m.group(3)}")
        return f"{ym}-{int(m.group(1)):02d}" if ym and "-" in ym else ym
    m = re.match(r"((?:19|20)\d{2})-(\d{2})-(\d{2})", s)
    if m:
        return s[:10]
    return parse_date(s)


def extract_certificate(doc: ParsedDocument, profile_name: str | None) -> Extracted | None:
    lines = [ln.text for ln in doc.lines]
    text = "\n".join(lines)
    data: dict = {"name": None, "issuer": None, "credential_id": None, "issued": None, "holder": None}

    m = re.search(r"certificate\s*(?:id|no\.?|number)\s*:?\s*([A-Za-z0-9-]+)", text, re.I)
    if m:
        data["credential_id"] = m.group(1)
    m = re.search(rf"issued(?:\s+on)?\s*:?\s*({_DATE_WORDS})", text, re.I)
    if m:
        data["issued"] = _full_date(m.group(1))
    for i, ln in enumerate(lines):
        low = ln.lower()
        if ("awarded to" in low or "certify that" in low) and i + 1 < len(lines):
            data["holder"] = lines[i + 1].strip()
        if ("completed" in low or "program in" in low or "course in" in low) and i + 1 < len(lines):
            data["name"] = data["name"] or lines[i + 1].strip()
    m = re.search(r"property of ([A-Z][\w&.' ]+?)[,.]", text)
    if m:
        data["issuer"] = m.group(1).strip()
    if not data["name"]:
        return None

    confidence = "high" if data["credential_id"] and data["issued"] and data["issuer"] else "medium"
    if profile_name and data["holder"] and data["holder"].lower() != profile_name.lower():
        data["holder_mismatch"] = True
        confidence = "low"
    return Extracted("certification", data, doc.lines, confidence)


def extract_licenses(section: Section) -> list[Extracted]:
    """A licence block is kept as one fact; 'Key: value' lines become fields, the rest become details."""
    if not section.lines:
        return []
    fields: dict[str, str] = {}
    details: list[str] = []
    for ln in section.lines:
        for part in re.split(r"\s+•\s+", ln.text):
            kv = re.match(r"([A-Za-z .&/-]{2,30}?)\s*:\s*(.+)", part)
            if kv:
                fields[kv.group(1).strip().lower()] = kv.group(2).strip()
            else:
                details.append(part.strip())
    name = fields.get("license") or fields.get("licence") or (details[0] if details else section.heading)
    data = {
        "name": name,
        "kind": "license",
        "issuer": next((d.replace("Licensed by", "").strip() for d in details if d.lower().startswith("licensed by")),
                       None),
        "credential_id": fields.get("hpr no.") or fields.get("hpr no") or fields.get("registration no"),
        "validity": fields.get("validity"),
        "fields": fields,
        "details": [d for d in details if d != name],
    }  # fmt: skip
    return [Extracted("certification", data, section.lines, "medium")]
