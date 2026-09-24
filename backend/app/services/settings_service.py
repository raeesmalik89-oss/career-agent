import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import Actor
from app.db.models import SettingsVersion
from app.schemas.settings import UserSettings
from app.services import audit


def latest(db: Session, user_id: uuid.UUID) -> SettingsVersion | None:
    return db.scalars(
        select(SettingsVersion)
        .where(SettingsVersion.user_id == user_id)
        .order_by(SettingsVersion.version.desc())
        .limit(1)
    ).first()


def get_effective(db: Session, user_id: uuid.UUID) -> tuple[UserSettings, int]:
    row = latest(db, user_id)
    if row is None:
        return UserSettings(), 0
    return (
        UserSettings(
            preferences=row.preferences,
            scoring_weights=row.scoring_weights,
            policy=row.policy,
            schedules=row.schedules,
            notifications=row.notifications or {},
            ai=row.ai or {},
        ),
        row.version,
    )


def save(
    db: Session, user_id: uuid.UUID, new: UserSettings, *, actor: Actor, request_id: str | None = None
) -> SettingsVersion:
    """Settings are never updated in place: each save is a new immutable version, audited with a diff."""
    current, version = get_effective(db, user_id)
    data = new.model_dump(mode="json")
    row = SettingsVersion(id=uuid.uuid4(), user_id=user_id, version=version + 1, **data)
    db.add(row)
    old = current.model_dump(mode="json")
    changed = {section: {k: v for k, v in data[section].items() if old[section].get(k) != v} for section in data}
    changed = {k: v for k, v in changed.items() if v}
    audit.record(
        db,
        action="settings.update",
        actor=actor,
        user_id=user_id,
        entity_type="settings_versions",
        entity_id=row.id,
        before={s: {k: old[s][k] for k in changed[s]} for s in changed},
        after=changed,
        request_id=request_id,
    )
    return row
