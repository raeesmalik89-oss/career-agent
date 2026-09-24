"""Five-field cron expressions (minute hour day-of-month month day-of-week), evaluated in a named time zone.

Supports *, lists (1,5), ranges (1-5), steps (*/15, 0-30/10) and 0 or 7 for Sunday. Day-of-month and day-of-week
combine the way classic cron does: if both are restricted, either one matching is enough.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FIELDS = (("minute", 0, 59), ("hour", 0, 23), ("day", 1, 31), ("month", 1, 12), ("weekday", 0, 7))
DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
SEARCH_LIMIT = timedelta(days=366)


class CronError(ValueError):
    pass


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CronError(f"unknown time zone {name!r}") from exc


def _field(text: str, name: str, lo: int, hi: int) -> frozenset[int]:
    values: set[int] = set()
    for part in text.split(","):
        body, _, step_s = part.partition("/")
        step = 1
        if step_s:
            if not step_s.isdigit() or int(step_s) < 1:
                raise CronError(f"bad step in {name}: {part!r}")
            step = int(step_s)
        if body == "*":
            start, end = lo, hi
        elif "-" in body:
            a, _, b = body.partition("-")
            if not (a.isdigit() and b.isdigit()):
                raise CronError(f"bad range in {name}: {part!r}")
            start, end = int(a), int(b)
        elif body.isdigit():
            start = int(body)
            end = hi if step_s else start
        else:
            raise CronError(f"bad {name} value {part!r}")
        if not (lo <= start <= end <= hi):
            raise CronError(f"{name} out of range {lo}-{hi}: {part!r}")
        values.update(range(start, end + 1, step))
    return frozenset(values)


@dataclass(frozen=True)
class Cron:
    expr: str
    minute: frozenset[int]
    hour: frozenset[int]
    day: frozenset[int]
    month: frozenset[int]
    weekday: frozenset[int]  # 0 = Sunday
    day_any: bool
    weekday_any: bool

    def matches(self, t: datetime) -> bool:
        return t.minute in self.minute and t.hour in self.hour and t.month in self.month and self._day_ok(t)

    def _walk(self, start_local: datetime, direction: int) -> datetime:
        """Minute-by-minute is simple and exact; skipping non-matching hours/days keeps it fast."""
        t = start_local.replace(second=0, microsecond=0)
        stop = start_local + direction * SEARCH_LIMIT
        while (t <= stop) if direction > 0 else (t >= stop):
            if t.month not in self.month or not self._day_ok(t):
                t = (
                    (t + timedelta(days=1)).replace(hour=0, minute=0)
                    if direction > 0
                    else (t.replace(hour=23, minute=59) - timedelta(days=1))
                )
                continue
            if t.hour not in self.hour:
                t = (
                    (t + timedelta(hours=1)).replace(minute=0)
                    if direction > 0
                    else (t.replace(minute=59) - timedelta(hours=1))
                )
                continue
            if t.minute in self.minute:
                return t
            t += direction * timedelta(minutes=1)
        raise CronError(f"{self.expr!r} never fires")

    def _day_ok(self, t: datetime) -> bool:
        dom = t.day in self.day
        dow = (t.isoweekday() % 7) in self.weekday
        if self.day_any or self.weekday_any:
            return dom and dow
        return dom or dow

    def next_after(self, after: datetime, tz: str) -> datetime:
        """First fire time strictly after `after` (aware datetime). Returned in UTC."""
        z = zone(tz)
        local = after.astimezone(z).replace(tzinfo=None) + timedelta(minutes=1)
        return _to_utc(self._walk(local, 1), z)

    def previous_at_or_before(self, at: datetime, tz: str) -> datetime:
        """Latest fire time at or before `at` (aware datetime). Returned in UTC."""
        z = zone(tz)
        local = at.astimezone(z).replace(tzinfo=None)
        return _to_utc(self._walk(local, -1), z)

    def describe(self) -> str:
        """Plain-English summary for the common shapes; falls back to the expression."""
        if len(self.minute) == 60 and len(self.hour) == 24:
            return "every minute"
        if len(self.hour) == 24 and len(self.minute) == 1:
            return f"every hour at :{min(self.minute):02d}"
        if len(self.minute) == 1 and self.day_any and len(self.month) == 12:
            m = min(self.minute)
            times = ", ".join(f"{h:02d}:{m:02d}" for h in sorted(self.hour))
            if self.weekday_any:
                return f"daily at {times}"
            days = ", ".join(DAY_NAMES[d] for d in sorted(self.weekday))
            return f"{days} at {times}"
        return self.expr


def _to_utc(naive_local: datetime, z: ZoneInfo) -> datetime:
    return naive_local.replace(tzinfo=z).astimezone(UTC)


def parse(expr: str) -> Cron:
    parts = expr.split()
    if len(parts) != 5:
        raise CronError(f"cron needs 5 fields (minute hour day month weekday), got {expr!r}")
    sets = [_field(p, name, lo, hi) for p, (name, lo, hi) in zip(parts, FIELDS, strict=True)]
    weekday = frozenset(d % 7 for d in sets[4])
    return Cron(
        expr=" ".join(parts),
        minute=sets[0],
        hour=sets[1],
        day=sets[2],
        month=sets[3],
        weekday=weekday,
        day_any=parts[2] == "*",
        weekday_any=parts[4] == "*",
    )
