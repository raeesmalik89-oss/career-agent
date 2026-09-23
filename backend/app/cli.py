"""Admin CLI.

python -m app.cli gen-keys                         print fresh JWT_SECRET / MASTER_KEY values
python -m app.cli seed                             seed the job-source registry (idempotent)
python -m app.cli create-owner --email E --name N  create the owner account (password prompted)
"""

import argparse
import getpass
import secrets
import sys

from sqlalchemy import select

from app.core.crypto import generate_master_key
from app.core.security import hash_password
from app.db.enums import Actor, Role
from app.db.models import User
from app.db.session import get_sessionmaker
from app.schemas.settings import UserSettings
from app.services import audit, settings_service
from app.services.seed import seed_sources

MIN_PASSWORD = 12


def gen_keys() -> None:
    print(f"JWT_SECRET={secrets.token_urlsafe(48)}")
    print(f"MASTER_KEY={generate_master_key()}")


def seed() -> None:
    from agents.resume_agent.agent import sync_taxonomy
    from agents.taxonomy import get_taxonomy

    with get_sessionmaker()() as db:
        added = seed_sources(db)
        skills = sync_taxonomy(db, get_taxonomy())
        db.commit()
    print(f"seeded {added} new job sources; {len(skills)} skills in taxonomy")


def set_password(email: str) -> None:
    password = getpass.getpass("New password (min 12 chars): ")
    if len(password) < MIN_PASSWORD:
        sys.exit(f"password must be at least {MIN_PASSWORD} characters")
    with get_sessionmaker()() as db:
        user = _user(db, email)
        user.password_hash = hash_password(password)
        user.failed_logins, user.locked_until = 0, None
        audit.record(db, action="user.set_password", actor=Actor.system, actor_detail="cli", user_id=user.id,
                     entity_type="users", entity_id=user.id)  # fmt: skip
        db.commit()
    print("password updated")


def _user(db, email: str) -> User:
    user = db.scalars(select(User).where(User.email == email.lower())).first()
    if user is None:
        sys.exit(f"no user {email}")
    return user


def import_profile(email: str, paths: list[str], reanalyze: bool) -> None:
    from agents.resume_agent.agent import DocumentInput, ResumeAnalyzerAgent, ResumeAnalyzerInput

    with get_sessionmaker()() as db:
        user = _user(db, email)
        payload = ResumeAnalyzerInput(
            user_id=user.id, documents=[DocumentInput(path=p) for p in paths], reanalyze=reanalyze
        )
        result = ResumeAnalyzerAgent().run(payload, db, user_id=user.id)
        audit.record(db, action="resume.import", actor=Actor.user, actor_detail="cli", user_id=user.id,
                     entity_type="agent_runs", entity_id=result.run_id, after={"files": len(paths)})  # fmt: skip
        db.commit()
    for a in result.actions:
        print(f"  {a.type:<24} {a.target or ''} {a.detail}")
    for e in result.errors:
        print(f"  ERROR {e.code}: {e.message}")
    print(f"run {result.run_id}: {'ok' if result.ok else 'with errors'}")


def report(email: str, out: str | None) -> None:
    import json

    from agents.resume_agent.report import build_report
    from agents.taxonomy import get_taxonomy

    with get_sessionmaker()() as db:
        data = build_report(db, _user(db, email).id, get_taxonomy())
    text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"report written to {out}")
    else:
        print(text)


def create_owner(email: str, name: str, password: str | None) -> None:
    password = password or getpass.getpass("Owner password (min 12 chars): ")
    if len(password) < MIN_PASSWORD:
        sys.exit(f"password must be at least {MIN_PASSWORD} characters")
    with get_sessionmaker()() as db:
        if db.scalars(select(User).where(User.email == email.lower())).first():
            sys.exit("a user with that email already exists")
        user = User(email=email.lower(), display_name=name, role=Role.owner, password_hash=hash_password(password))
        db.add(user)
        db.flush()
        settings_service.save(db, user.id, UserSettings(), actor=Actor.system)
        audit.record(
            db,
            action="user.create_owner",
            actor=Actor.system,
            actor_detail="cli",
            user_id=user.id,
            entity_type="users",
            entity_id=user.id,
        )
        db.commit()
    print(f"owner created: {email}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gen-keys")
    sub.add_parser("seed")
    co = sub.add_parser("create-owner")
    co.add_argument("--email", required=True)
    co.add_argument("--name", required=True)
    co.add_argument("--password", help="non-interactive use only (e.g. CI); prefer the prompt")
    sp = sub.add_parser("set-password")
    sp.add_argument("--email", required=True)
    ip = sub.add_parser("import-profile")
    ip.add_argument("--email", required=True)
    ip.add_argument("--reanalyze", action="store_true")
    ip.add_argument("files", nargs="+")
    rp = sub.add_parser("report")
    rp.add_argument("--email", required=True)
    rp.add_argument("--out")
    args = p.parse_args(argv)
    if args.cmd == "gen-keys":
        gen_keys()
    elif args.cmd == "seed":
        seed()
    elif args.cmd == "set-password":
        set_password(args.email)
    elif args.cmd == "import-profile":
        import_profile(args.email, args.files, args.reanalyze)
    elif args.cmd == "report":
        report(args.email, args.out)
    else:
        create_owner(args.email, args.name, args.password)


if __name__ == "__main__":
    main()
