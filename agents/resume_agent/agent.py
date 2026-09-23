"""Resume Analyzer Agent: documents in, verified-fact candidates + resume intelligence out."""

import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from agents.base import Agent, AgentContext
from agents.resume_agent import extract as X
from agents.resume_agent.analysis import analyze_document, skill_mentions
from agents.resume_agent.certificates import extract_certificate, extract_licenses, looks_like_certificate
from agents.resume_agent.merge import fact_key, merge_data, same_entity
from agents.resume_agent.parsing import ParsedDocument, UnsupportedDocument, parse_bytes
from agents.resume_agent.report import build_report
from agents.resume_agent.sections import split_sections
from agents.skill_levels import recompute_user_skills
from agents.taxonomy import Taxonomy, get_taxonomy
from app.db.enums import Confidence, FactType, FileFormat, ResumeKind, SourceType
from app.db.models import ProfileFact, ResumeProfile, ResumeVersion, Skill
from app.services import storage

_CONF_RANK = {"low": 0, "medium": 1, "high": 2}


class DocumentInput(BaseModel):
    path: str
    label: str | None = None
    filename: str | None = None  # original name when `path` is a content-addressed copy


class ResumeAnalyzerInput(BaseModel):
    user_id: uuid.UUID
    documents: list[DocumentInput] = Field(min_length=1)  # first document = primary resume
    reanalyze: bool = False


def sync_taxonomy(db, taxonomy: Taxonomy) -> dict[str, Skill]:
    """Upsert the YAML taxonomy into `skills`; returns canonical_name -> Skill."""
    existing = {s.canonical_name: s for s in db.scalars(select(Skill))}
    for sd in taxonomy.skills.values():
        row = existing.get(sd.key)
        if row is None:
            row = Skill(canonical_name=sd.key)
            db.add(row)
            existing[sd.key] = row
        row.display_name, row.category = sd.name, sd.category
        row.aliases, row.adjacent, row.outdated_reason = list(sd.aliases), list(sd.adjacent), sd.outdated
    db.flush()
    return existing


class ResumeAnalyzerAgent(Agent[ResumeAnalyzerInput]):
    name = "resume_analyzer"

    def __init__(self, taxonomy: Taxonomy | None = None):
        self.taxonomy = taxonomy or get_taxonomy()

    def summarize_input(self, payload: ResumeAnalyzerInput) -> str:
        return f"{len(payload.documents)} documents; reanalyze={payload.reanalyze}"

    # ------------------------------------------------------------------ execute

    def execute(self, payload: ResumeAnalyzerInput, ctx: AgentContext) -> tuple[dict[str, Any], Confidence | None]:
        db, user_id = ctx.db, payload.user_id
        sync_taxonomy(db, self.taxonomy)
        profile = db.scalars(select(ResumeProfile).where(ResumeProfile.user_id == user_id)).first()
        facts = {(f.fact_type.value, f.fact_key): f for f in db.scalars(
            select(ProfileFact).where(ProfileFact.user_id == user_id))}  # fmt: skip

        for doc_in in payload.documents:
            path = Path(doc_in.path)
            filename = doc_in.filename or path.name
            try:
                data = path.read_bytes()
                doc = parse_bytes(data, filename)
            except (OSError, UnsupportedDocument) as exc:
                ctx.error("document_unreadable", f"{filename}: {exc}")
                continue

            version = db.scalars(select(ResumeVersion).where(
                ResumeVersion.user_id == user_id, ResumeVersion.sha256 == doc.sha256)).first()  # fmt: skip
            if version is not None and not payload.reanalyze:
                ctx.act("skip_already_analyzed", target=filename, version_id=str(version.id))
                continue

            is_cert = looks_like_certificate(doc)
            if profile is None:
                profile = ResumeProfile(user_id=user_id, name="(unknown)")
                db.add(profile)
                db.flush()
            label = doc_in.label or Path(filename).stem
            if version is None:
                version = ResumeVersion(
                    user_id=user_id, profile_id=profile.id, sha256=doc.sha256, label=label,
                    kind=ResumeKind.certificate if is_cert else ResumeKind.source,
                    original_filename=filename, format=FileFormat(doc.format),
                    file_uri=storage.save_document(data, doc.sha256, Path(filename).suffix),
                    created_by_agent_run=ctx.run_id,
                )  # fmt: skip
                db.add(version)
                db.flush()

            extracted, parsed = self._extract(doc, is_cert, profile.name)
            version.parsed = parsed
            ctx.act("parsed_document", target=filename, kind=version.kind.value, layout=doc.layout,
                    facts=len(extracted))  # fmt: skip

            ref_base = {"document_id": str(version.id), "label": label}
            for e in extracted:
                self._upsert(db, ctx, facts, user_id, e, ref_base, doc)

            if not is_cert:
                self._update_profile(profile, extracted, parsed)

        recompute_user_skills(db, user_id, self.taxonomy)
        db.flush()
        report = build_report(db, user_id, self.taxonomy)
        conflicts = len(report["conflicts"])
        confidence = Confidence.high if not conflicts and not ctx.errors else Confidence.medium
        return report, confidence

    # ------------------------------------------------------------------ helpers

    def _extract(self, doc: ParsedDocument, is_cert: bool, profile_name: str | None) -> tuple[list[X.Extracted], dict]:
        if is_cert:
            cert = extract_certificate(doc, None if profile_name == "(unknown)" else profile_name)
            parsed = {"text": doc.text, "layout": doc.layout, "document_type": "certificate", "warnings": doc.warnings}
            if cert:
                cert.data["source_document"] = "certificate_file"
            return ([cert] if cert else []), parsed

        sections = split_sections(doc.lines, doc.column_breaks)
        tax = self.taxonomy
        out: list[X.Extracted] = X.extract_personal(sections, doc.lines)
        work: list[X.Extracted] = []
        for s in sections:
            if s.name == "experience":
                work += X.extract_experience(s, tax)
            elif s.name == "projects":
                work += X.extract_projects(s, tax)
            elif s.name == "education":
                out += X.extract_education(s)
            elif s.name == "certifications":
                out += X.extract_certifications_section(s)
            elif s.name == "licenses":
                out += extract_licenses(s)
        out += work + X.extract_achievements(work)

        mentions = skill_mentions(sections, tax)
        for key, m in mentions.items():
            sd = tax.skills[key]
            out.append(X.Extracted(
                "skill_claim",
                {"skill": key, "name": sd.name, "category": sd.category,
                 "evidence": m.evidence,
                 "sections": sorted(m.sections), "surfaces": sorted(set(m.surfaces)),
                 "implied_by": sorted(m.implied_by)},
                m.lines[:3], "high" if m.surfaces else "medium",
            ))  # fmt: skip
        parsed = {
            "text": doc.text,
            "document_type": "resume",
            "summary": X.extract_summary(sections),
            "analysis": analyze_document(doc, sections, mentions, tax),
        }
        return out, parsed

    def _upsert(self, db, ctx: AgentContext, facts: dict, user_id: uuid.UUID, e: X.Extracted, ref_base: dict,
                doc: ParsedDocument) -> None:  # fmt: skip
        key = fact_key(e)
        if (e.kind, key) not in facts and e.kind in ("project", "experience", "education"):
            candidates = [
                (fkey, f)
                for (ftype, fkey), f in facts.items()
                if ftype == e.kind and same_entity(e.kind, f.data, e.data)
            ]
            if candidates:
                # Most specific wins: "Mubarak Hospital" beats a grouped "Mubarak Hospital • IBD DHQ ... • ...".
                key = min(candidates, key=lambda c: len(str(c[1].data.get("organization") or c[1].data)))[0]
        first = e.lines[0] if e.lines else None
        ref = {**ref_base, "page": first.page if first else None,
               "start": first.start if first else None, "end": e.lines[-1].end if e.lines else None,
               "snippet": doc.text[first.start: e.lines[-1].end][:300] if first else None}  # fmt: skip
        existing = facts.get((e.kind, key))
        if existing is None:
            fact = ProfileFact(
                user_id=user_id, fact_type=FactType(e.kind), fact_key=key[:200], data=e.data,
                source_type=SourceType.resume, source_ref={"sources": [ref]}, confidence=Confidence(e.confidence),
            )  # fmt: skip
            db.add(fact)
            facts[(e.kind, key)] = fact
            return
        sources = existing.source_ref.get("sources", [])
        if any(s.get("document_id") == ref["document_id"] for s in sources):
            return  # same document re-analysed: keep the first extraction
        old_label = sources[0].get("label", "?") if sources else "?"
        merged, conflicts = merge_data(e.kind, existing.data, e.data, old_label, ref["label"])
        existing.data = merged
        existing.source_ref = {"sources": [*sources, ref]}
        if conflicts:
            existing.confidence = Confidence.low
            ctx.act("conflict_detected", target=f"{e.kind}:{key}", fields=[c["field"] for c in conflicts])
        elif _CONF_RANK[e.confidence] > _CONF_RANK[existing.confidence.value]:
            existing.confidence = Confidence(e.confidence)

    @staticmethod
    def _update_profile(profile: ResumeProfile, extracted: list[X.Extracted], parsed: dict) -> None:
        """Fill only empty profile fields; the first (primary) document wins."""
        personal = {e.data["field"]: e.data["value"] for e in extracted if e.kind == "personal"}
        if profile.name == "(unknown)" and personal.get("name"):
            profile.name = personal["name"]
        profile.location = profile.location or personal.get("location")
        contacts = dict(profile.contacts or {})
        for k in ("email", "phone"):
            if personal.get(k):
                contacts.setdefault(k, personal[k])
        profile.contacts = contacts
        links = dict(profile.links or {})
        for k in ("linkedin", "github"):
            if personal.get(k):
                links.setdefault(k, personal[k])
        profile.links = links
        profile.summary = profile.summary or parsed.get("summary")
