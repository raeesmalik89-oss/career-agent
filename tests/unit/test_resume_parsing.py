import io
import zipfile

import pytest

from agents.resume_agent import extract as X
from agents.resume_agent.analysis import analyze_document, skill_mentions
from agents.resume_agent.certificates import extract_certificate, looks_like_certificate
from agents.resume_agent.parsing import UnsupportedDocument, parse_bytes
from agents.resume_agent.sections import split_sections
from agents.taxonomy import get_taxonomy
from tests.fixtures.resumes import (
    CERTIFICATE_TXT,
    PRIMARY_TXT,
    docx_bytes,
    pdf_bytes,
    two_column_pdf_bytes,
)

TAX = get_taxonomy()


def _parse(text: str = PRIMARY_TXT, name: str = "cv.txt"):
    doc = parse_bytes(text.encode(), name)
    return doc, split_sections(doc.lines, doc.column_breaks)


# ------------------------------------------------------------------ parsing


def test_txt_lines_keep_offsets():
    doc, _ = _parse()
    for ln in doc.lines:
        assert doc.text[ln.start : ln.end] == ln.text


@pytest.mark.parametrize("builder, name", [(docx_bytes, "cv.docx"), (pdf_bytes, "cv.pdf")])
def test_docx_and_pdf_parse_to_same_sections(builder, name):
    doc = parse_bytes(builder(PRIMARY_TXT), name)
    names = [s.name for s in split_sections(doc.lines, doc.column_breaks)]
    assert names[:6] == ["header", "summary", "skills", "experience", "projects", "education"]


def test_docx_list_paragraphs_become_bullets():
    doc = parse_bytes(docx_bytes(PRIMARY_TXT), "cv.docx")
    assert any(ln.text.startswith("• Migrated 40 services") for ln in doc.lines)


def test_two_column_pdf_is_split_and_flagged():
    doc = parse_bytes(two_column_pdf_bytes(), "cv.pdf")
    assert doc.layout == "two_column" and doc.column_breaks
    sections = split_sections(doc.lines, doc.column_breaks)
    exp = next(s for s in sections if s.name == "experience")
    assert all("Tool" not in ln.text for ln in exp.lines)  # sidebar did not leak into the main column
    assert any("two-column" in w.lower() for w in doc.warnings)


@pytest.mark.parametrize(
    "data, name, message",
    [
        (b"hello", "cv.exe", "unsupported"),
        (b"not a pdf", "cv.pdf", "does not look like a PDF"),
        (b"not a zip", "cv.docx", "does not look like a DOCX"),
        (b"\xff\xfe\xfa", "cv.txt", "UTF-8"),
        (b"x" * (10 * 1024 * 1024 + 1), "cv.txt", "10 MB"),
    ],
    ids=["extension", "fake-pdf", "fake-docx", "not-utf8", "too-large"],
)
def test_rejects_bad_files(data, name, message):
    with pytest.raises(UnsupportedDocument, match=message):
        parse_bytes(data, name)


def test_rejects_docx_zip_bomb():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", b"\0" * (51 * 1024 * 1024))
    with pytest.raises(UnsupportedDocument, match="50 MB"):
        parse_bytes(buf.getvalue(), "bomb.docx")


# ------------------------------------------------------------------ sections


def test_name_line_is_not_a_heading_but_later_caps_headings_are():
    doc = parse_bytes(b"JOHN DOE\nSUMMARY\nHello there.\nNORWEGIAN PROFESSIONAL LICENSE\nLicense: X\n", "a.txt")
    names = [s.name for s in split_sections(doc.lines)]
    assert names == ["header", "summary", "licenses"]


# ------------------------------------------------------------------ extraction


@pytest.mark.parametrize(
    "raw, expected",
    [("Aug 2024", "2024-08"), ("2020", "2020"), ("Present", "present"), ("Sept 2021", "2021-09"), ("soon", None)],
)
def test_parse_date(raw, expected):
    assert X.parse_date(raw) == expected


def test_months_between():
    assert X.months_between("2024-08", "2025-08") == 13
    assert X.months_between("2020", "2024") == 48
    assert X.months_between("2024-01", None) is None


def test_personal_fields():
    doc, sections = _parse()
    got = {e.data["field"]: e.data["value"] for e in X.extract_personal(sections, doc.lines)}
    assert got["name"] == "Ayesha Khan"
    assert got["email"] == "ayesha.khan@example.com"
    assert got["github"] == "github.com/ayesha-example"
    assert got["linkedin"] == "linkedin.com/in/ayesha-khan-example"
    assert got["location"] == "Lahore, Pakistan"
    assert [lang["language"] for lang in got["languages"]] == ["English", "Urdu"]


def test_experience_blocks_and_wrapped_bullets():
    _, sections = _parse()
    exp = X.extract_experience(next(s for s in sections if s.name == "experience"), TAX)
    assert [e.data["title"] for e in exp] == ["DevOps Engineer", "Junior DevOps Intern"]
    first = exp[0].data
    assert first["organization"] == "Acme Cloud Ltd" and first["start"] == "2023-01" and first["end"] == "present"
    assert len(first["responsibilities"]) == 2
    assert first["responsibilities"][1].endswith("image scanning using Trivy.")  # wrapped line re-joined
    assert {"kubernetes", "terraform", "github_actions", "trivy"} <= set(first["technologies"])
    assert exp[1].data["is_training"] is True and exp[0].data["is_training"] is False
    assert exp[0].confidence == "high"


def test_projects_use_tech_line():
    _, sections = _parse()
    proj = X.extract_projects(next(s for s in sections if s.name == "projects"), TAX)
    assert proj[0].data["name"] == "Kubernetes Observability Stack"
    assert {"prometheus", "grafana", "helm", "kubernetes"} <= set(proj[0].data["technologies"])


def test_education_with_grade():
    _, sections = _parse()
    edu = X.extract_education(next(s for s in sections if s.name == "education"))
    assert edu[0].data["qualification"] == "BS Computer Science"
    assert edu[0].data["institution"] == "University of the Punjab, Lahore"
    assert edu[0].data["date"] == "2022" and edu[0].data["grade"] == "3.4/4.0"


def test_achievements_need_numbers():
    _, sections = _parse()
    exp = X.extract_experience(next(s for s in sections if s.name == "experience"), TAX)
    ach = X.extract_achievements(exp)
    assert len(ach) == 1 and "40 services" in ach[0].data["text"]


# ------------------------------------------------------------------ certificates


def test_certificate_document():
    doc = parse_bytes(CERTIFICATE_TXT.encode(), "cert.txt")
    assert looks_like_certificate(doc)
    cert = extract_certificate(doc, "Ayesha Khan")
    assert cert.data["name"] == "Certificate in DevOps and Cloud"
    assert cert.data["credential_id"] == "9999-1" and cert.data["issued"] == "2025-09-16"
    assert cert.data["issuer"] == "Example Academy" and cert.confidence == "high"


def test_certificate_for_someone_else_is_low_confidence():
    cert = extract_certificate(parse_bytes(CERTIFICATE_TXT.encode(), "c.txt"), "Somebody Else")
    assert cert.data["holder_mismatch"] is True and cert.confidence == "low"


def test_resume_is_not_a_certificate():
    doc, _ = _parse()
    assert not looks_like_certificate(doc)


# ------------------------------------------------------------------ analysis


def test_analysis_findings():
    doc, sections = _parse()
    mentions = skill_mentions(sections, TAX)
    a = analyze_document(doc, sections, mentions, TAX)
    missing = {m["skill"] for m in a["missing_evidence"]}
    assert "datadog" in missing and "azure" in missing  # listed, never used
    assert "kubernetes" not in missing  # used in experience
    assert {d["skill"] for d in a["duplicate_skills"]} == {"python"}  # "Python" repeated in the skills list
    assert [o["skill"] for o in a["outdated_skills"]] == ["docker_swarm"]
    assert mentions["go"].evidence == "listed"  # ambiguous 'Go' only counted inside the skills list
    assert mentions["aws"].implied_by == set() and "eks" in mentions
    assert a["missing_sections"] == []
