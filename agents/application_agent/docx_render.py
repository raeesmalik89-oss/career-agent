"""ATS-safe DOCX output: one column, real headings, plain bullets, no tables, text boxes or images."""

import io
import re

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt


def _doc() -> Document:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    for s in doc.sections:
        s.left_margin = s.right_margin = Pt(54)
        s.top_margin = s.bottom_margin = Pt(46)
    return doc


def _heading(doc: Document, text: str) -> None:
    h = doc.add_heading(text.upper(), level=2)
    for r in h.runs:
        r.font.size = Pt(11)


def _bytes(doc: Document) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def render_resume(resume: dict) -> bytes:
    doc = _doc()
    h = resume["header"]
    title = doc.add_heading(h.get("name", {}).get("text", ""), level=1)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    contact = " | ".join(h[k]["text"] for k in ("location", "email", "phone", "linkedin", "github") if k in h)
    if contact:
        doc.add_paragraph(contact)

    if resume.get("summary"):
        _heading(doc, "Summary")
        doc.add_paragraph(resume["summary"]["text"])

    if resume["skills"]:
        _heading(doc, "Skills")
        for g in resume["skills"]:
            p = doc.add_paragraph()
            p.add_run(f"{g['group']}: ").bold = True
            p.add_run(", ".join(s["text"] for s in g["items"]))

    if resume["experience"]:
        _heading(doc, "Experience")
        for e in resume["experience"]:
            p = doc.add_paragraph()
            p.add_run(e["title"]).bold = True
            p.add_run(f" | {e['organization']}")
            if e.get("location"):  # older stored resumes have no location
                p.add_run(f" | {e['location']}")
            if e["dates"]:
                p.add_run(f" | {e['dates']}")
            for b in e["bullets"]:
                doc.add_paragraph(b["text"], style="List Bullet")

    if resume["projects"]:
        _heading(doc, "Projects")
        for pr in resume["projects"]:
            p = doc.add_paragraph()
            p.add_run(pr["name"]).bold = True
            if pr["technologies"]:
                p.add_run(" | " + ", ".join(pr["technologies"]))
            if pr.get("repo"):
                p.add_run(f" | {pr['repo']}")
            for b in pr["bullets"]:
                doc.add_paragraph(b["text"], style="List Bullet")

    if resume["education"]:
        _heading(doc, "Education")
        for e in resume["education"]:
            line = f"{e['qualification']}, {e['institution']}"
            line += f" | {e['date']}" if e["date"] else ""
            line += f" | {e['grade']}" if e.get("grade") else ""
            doc.add_paragraph(line)

    if resume["certifications"]:
        _heading(doc, "Certifications & licences")
        for c in resume["certifications"]:
            parts = [
                c["name"],
                c.get("issuer"),
                c.get("issued"),
                f"ID {c['credential_id']}" if c.get("credential_id") else None,
            ]
            doc.add_paragraph(" | ".join(x for x in parts if x), style="List Bullet")

    langs = resume.get("languages")
    if langs and isinstance(langs["items"], list):
        _heading(doc, "Languages")
        doc.add_paragraph(
            ", ".join(f"{x.get('language')} ({x.get('level')})" for x in langs["items"] if isinstance(x, dict))
        )
    return _bytes(doc)


def render_cover_letter(paragraphs: list[str]) -> bytes:
    doc = _doc()
    for text in paragraphs:
        doc.add_paragraph(text)
    return _bytes(doc)


def safe_filename(*parts: str) -> str:
    return "_".join(re.sub(r"[^A-Za-z0-9]+", "-", p).strip("-")[:40] for p in parts if p) or "document"
