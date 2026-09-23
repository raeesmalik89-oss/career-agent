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
    with get_sessionmaker()() as db:
        added = seed_sources(db)
        db.commit()
    print(f"seeded {added} new job sources")


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
    args = p.parse_args(argv)
    if args.cmd == "gen-keys":
        gen_keys()
    elif args.cmd == "seed":
        seed()
    else:
        create_owner(args.email, args.name, args.password)


if __name__ == "__main__":
    main()
