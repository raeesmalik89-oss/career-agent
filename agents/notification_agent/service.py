"""Notifications: always on the dashboard; optionally also by email / Telegram.

- dedup_key makes a notification idempotent (e.g. one "new match" per job, however often the scan re-runs).
- External channels only get severities >= external_min_severity (or channels explicitly requested, like the
  daily digest email), respect quiet hours (urgent ones excepted) and are retried by housekeeping.
- Delivery state lives in notifications.delivered[channel] = {status: sent|failed|deferred, attempts, error, at}.
"""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Notification
from app.schemas.settings import Notifications, UserSettings
from app.services import settings_service
from app.services.secrets import get_secret
from integrations.notify import DeliveryError, Message
from integrations.notify import email as email_channel
from integrations.notify import telegram as telegram_channel

SEVERITY_RANK = {"info": 0, "important": 1, "urgent": 2}
EXTERNAL = ("email", "telegram")
MAX_ATTEMPTS = 5
RETRY_WINDOW = timedelta(days=3)


def _send_email(db: Session, user_id: uuid.UUID, cfg: Notifications, msg: Message) -> None:
    email_channel.send(
        email_channel.SmtpConfig(
            host=cfg.smtp_host or "",
            port=cfg.smtp_port,
            username=cfg.smtp_username,
            password=get_secret(db, user_id, "smtp_password"),
            sender=str(cfg.email_from),
            to=str(cfg.email_to),
        ),
        msg,
    )


def _send_telegram(db: Session, user_id: uuid.UUID, cfg: Notifications, msg: Message) -> None:
    token = get_secret(db, user_id, "telegram_bot_token")
    if not token:
        raise DeliveryError("no Telegram bot token stored (set the telegram_bot_token secret)")
    telegram_channel.send(token, cfg.telegram_chat_id or "", msg)


# Tests replace these with fakes; production code never sends anywhere else.
SENDERS = {"email": _send_email, "telegram": _send_telegram}


def _enabled(cfg: Notifications) -> list[str]:
    return [c for c, on in (("email", cfg.email_enabled), ("telegram", cfg.telegram_enabled)) if on]


def channels_for(cfg: Notifications, severity: str, extra: tuple[str, ...] = ()) -> list[str]:
    wanted = SEVERITY_RANK[severity] >= SEVERITY_RANK[cfg.external_min_severity]
    return ["dashboard", *[c for c in _enabled(cfg) if wanted or c in extra]]


def in_quiet_hours(cfg: Notifications, now: datetime, tz: str) -> bool:
    start, end = cfg.quiet_hours_start, cfg.quiet_hours_end
    if start is None or end is None or start == end:
        return False
    hour = now.astimezone(ZoneInfo(tz)).hour
    return start <= hour < end if start < end else hour >= start or hour < end


def _absolute(cfg: Notifications, link: str | None) -> str | None:
    if not link:
        return None
    return cfg.dashboard_url.rstrip("/") + link if link.startswith("/") else None


def notify(
    db: Session,
    user_id: uuid.UUID,
    *,
    kind: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
    severity: str = "info",
    dedup_key: str | None = None,
    extra_channels: tuple[str, ...] = (),
    now: datetime | None = None,
    settings: UserSettings | None = None,
) -> Notification | None:
    """Create (and try to deliver) a notification. Returns None if dedup_key was already used."""
    if severity not in SEVERITY_RANK:
        raise ValueError(f"unknown severity {severity!r}")
    if (
        dedup_key
        and db.scalars(
            select(Notification.id).where(Notification.user_id == user_id, Notification.dedup_key == dedup_key)
        ).first()
    ):
        return None
    now = now or datetime.now(UTC)
    settings = settings or settings_service.get_effective(db, user_id)[0]
    n = Notification(
        id=uuid.uuid4(),
        user_id=user_id,
        dedup_key=dedup_key,
        kind=kind,
        severity=severity,
        title=title[:300],
        body=body,
        link=link,
        channels=channels_for(settings.notifications, severity, extra_channels),
        delivered={"dashboard": {"status": "sent", "at": now.isoformat()}},
        created_at=now,
    )
    try:
        with db.begin_nested():
            db.add(n)
    except IntegrityError:  # a concurrent run created the same dedup_key first
        return None
    deliver(db, n, settings=settings, now=now)
    return n


def deliver(
    db: Session,
    n: Notification,
    *,
    settings: UserSettings | None = None,
    now: datetime | None = None,
    ignore_quiet_hours: bool = False,
) -> dict:
    """Try every external channel that is not yet sent. Returns the updated delivery map."""
    now = now or datetime.now(UTC)
    settings = settings or settings_service.get_effective(db, n.user_id)[0]
    cfg = settings.notifications
    quiet = not ignore_quiet_hours and n.severity != "urgent" and in_quiet_hours(cfg, now, settings.schedules.timezone)
    state = dict(n.delivered or {})
    msg = Message(title=n.title, body=n.body or "", url=_absolute(cfg, n.link))
    for ch in n.channels:
        if ch not in EXTERNAL:
            continue
        cur = dict(state.get(ch) or {})
        attempts = int(cur.get("attempts", 0))
        if cur.get("status") == "sent" or attempts >= MAX_ATTEMPTS:
            continue
        if ch not in _enabled(cfg):
            cur.update(status="skipped", error="channel turned off in settings")
        elif quiet:
            cur.update(status="deferred", error="quiet hours")
        else:
            try:
                SENDERS[ch](db, n.user_id, cfg, msg)
                cur = {"status": "sent", "attempts": attempts + 1, "at": now.isoformat()}
            except DeliveryError as exc:
                cur = {"status": "failed", "attempts": attempts + 1, "error": str(exc)[:300], "at": now.isoformat()}
        state[ch] = cur
    n.delivered = state
    db.flush()
    return state


def retry_pending(db: Session, user_id: uuid.UUID, now: datetime | None = None) -> dict:
    """Housekeeping: re-try failed or deferred external deliveries from the last few days."""
    now = now or datetime.now(UTC)
    settings = settings_service.get_effective(db, user_id)[0]
    rows = db.scalars(
        select(Notification).where(Notification.user_id == user_id, Notification.created_at >= now - RETRY_WINDOW)
    ).all()
    counts = {"retried": 0, "sent": 0, "still_pending": 0}
    for n in rows:
        pending = [
            c
            for c in n.channels
            if c in EXTERNAL
            and (n.delivered or {}).get(c, {}).get("status") in (None, "failed", "deferred")
            and int((n.delivered or {}).get(c, {}).get("attempts", 0)) < MAX_ATTEMPTS
        ]
        if not pending:
            continue
        counts["retried"] += 1
        state = deliver(db, n, settings=settings, now=now)
        if all(state.get(c, {}).get("status") == "sent" for c in pending):
            counts["sent"] += 1
        else:
            counts["still_pending"] += 1
    return counts


def send_test(db: Session, user_id: uuid.UUID) -> dict:
    """A test message to every enabled channel, ignoring severity filters and quiet hours."""
    settings = settings_service.get_effective(db, user_id)[0]
    n = Notification(
        id=uuid.uuid4(),
        user_id=user_id,
        kind="test",
        severity="info",
        title="Test notification",
        body="If you can read this, Career Agent notifications reach you on this channel.",
        link="/notifications",
        channels=["dashboard", *_enabled(settings.notifications)],
        delivered={"dashboard": {"status": "sent", "at": datetime.now(UTC).isoformat()}},
        created_at=datetime.now(UTC),
    )
    db.add(n)
    db.flush()
    return deliver(db, n, settings=settings, ignore_quiet_hours=True)
