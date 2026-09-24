from datetime import UTC, datetime

import pytest

from scheduler.cron import CronError, parse

KHI = "Asia/Karachi"  # UTC+5, no DST


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def test_daily_in_karachi():
    c = parse("0 7 * * *")
    # 01:30 UTC = 06:30 PKT -> next 07:00 PKT = 02:00 UTC the same day
    assert c.next_after(utc(2026, 9, 24, 1, 30), KHI) == utc(2026, 9, 24, 2, 0)
    # exactly on the fire time: next is tomorrow, previous is now
    assert c.next_after(utc(2026, 9, 24, 2, 0), KHI) == utc(2026, 9, 25, 2, 0)
    assert c.previous_at_or_before(utc(2026, 9, 24, 2, 0), KHI) == utc(2026, 9, 24, 2, 0)
    assert c.previous_at_or_before(utc(2026, 9, 24, 1, 59), KHI) == utc(2026, 9, 23, 2, 0)


def test_weekly_sunday_and_steps_lists_ranges():
    sun = parse("0 10 * * 0")
    assert parse("0 10 * * 7").weekday == sun.weekday
    nxt = sun.next_after(utc(2026, 9, 24, 0, 0), KHI)  # Thursday
    assert nxt == utc(2026, 9, 27, 5, 0) and nxt.astimezone().isoweekday() in (7, 1)
    c = parse("*/15 9-17 * * 1-5")
    assert c.minute == {0, 15, 30, 45} and c.hour == set(range(9, 18)) and c.weekday == {1, 2, 3, 4, 5}
    assert parse("5,35 * * * *").next_after(utc(2026, 1, 1, 0, 6), "UTC") == utc(2026, 1, 1, 0, 35)


def test_dom_or_dow_like_classic_cron():
    c = parse("0 0 1 * 1")  # the 1st of the month OR any Monday
    assert c.matches(datetime(2026, 10, 1, 0, 0)) and c.matches(datetime(2026, 9, 28, 0, 0))
    assert not c.matches(datetime(2026, 9, 29, 0, 0))


def test_dst_zone():
    # New York springs forward on 2026-03-08: 02:30 local does not exist; like classic cron the run still happens
    # that day, right after the gap (03:30 EDT = 07:30 UTC), and is not skipped
    c = parse("30 2 * * *")
    assert c.next_after(utc(2026, 3, 8, 5, 0), "America/New_York") == utc(2026, 3, 8, 7, 30)
    assert c.next_after(utc(2026, 3, 8, 7, 30), "America/New_York") == utc(2026, 3, 9, 6, 30)  # 02:30 EDT


@pytest.mark.parametrize(
    "expr", ["", "* * * *", "60 * * * *", "* 24 * * *", "* * 0 * *", "* * * 13 *", "x * * * *", "*/0 * * * *",
             "5-1 * * * *", "0 0 31 2 *"],
)  # fmt: skip
def test_invalid(expr):
    with pytest.raises(CronError):
        c = parse(expr)
        c.next_after(utc(2026, 1, 1), "UTC")  # Feb 31 parses but never fires


def test_unknown_zone_and_describe():
    with pytest.raises(CronError, match="time zone"):
        parse("0 7 * * *").next_after(utc(2026, 1, 1), "Mars/Olympus")
    assert parse("0 7 * * *").describe() == "daily at 07:00"
    assert parse("0 10 * * 0").describe() == "Sunday at 10:00"
    assert parse("15 * * * *").describe() == "every hour at :15"
