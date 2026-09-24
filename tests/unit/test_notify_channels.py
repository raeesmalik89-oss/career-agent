import io
import urllib.error
from datetime import UTC, datetime

import pytest

from agents.notification_agent.service import channels_for, in_quiet_hours
from app.schemas.settings import Notifications, Schedules
from integrations.notify import DeliveryError, Message, scrub, telegram
from integrations.notify import email as email_channel

TOKEN = "123456:FAKE-token-for-tests"


def test_message_truncation_keeps_link():
    m = Message(title="T", body="x" * 5000, url="http://localhost:3000/jobs/1")
    text = m.plain(4000)
    assert len(text) <= 4000 and text.endswith("Open: http://localhost:3000/jobs/1") and "(truncated)" in text


def test_scrub():
    assert scrub(f"POST https://api.telegram.org/bot{TOKEN}/sendMessage failed", TOKEN) == (
        "POST https://api.telegram.org/bot***/sendMessage failed"
    )


def test_email_headers_cannot_be_injected():
    cfg = email_channel.SmtpConfig("smtp.example.com", 587, None, None, "agent@example.com", "me@example.com")
    em = email_channel.build(cfg, Message(title="Hi\r\nBcc: victim@example.com", body="b"))
    assert em["Bcc"] is None and "\n" not in em["Subject"]


def test_telegram_errors_never_contain_the_token(monkeypatch):
    def boom(req, timeout):
        assert req.full_url.startswith("https://api.telegram.org/bot")
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"description":"bad"}'))

    monkeypatch.setattr(telegram.urllib.request, "urlopen", boom)
    with pytest.raises(DeliveryError) as e:
        telegram.send(TOKEN, "12345", Message("t", "b"))
    assert TOKEN not in str(e.value) and "401" in str(e.value)

    def down(req, timeout):
        raise urllib.error.URLError(f"cannot reach {req.full_url}")

    monkeypatch.setattr(telegram.urllib.request, "urlopen", down)
    with pytest.raises(DeliveryError) as e:
        telegram.send(TOKEN, "12345", Message("t", "b"))
    assert TOKEN not in str(e.value)


def test_channel_routing_and_quiet_hours():
    cfg = Notifications(
        email_enabled=True, email_to="me@example.com", email_from="a@example.com", smtp_host="smtp.example.com",
        telegram_enabled=True, telegram_chat_id="42",
    )  # fmt: skip
    assert channels_for(cfg, "info") == ["dashboard"]
    assert channels_for(cfg, "info", ("email",)) == ["dashboard", "email"]
    assert channels_for(cfg, "important") == ["dashboard", "email", "telegram"]
    tz = Schedules().timezone
    assert in_quiet_hours(cfg, datetime(2026, 9, 24, 18, 30, tzinfo=UTC), tz)  # 23:30 PKT
    assert in_quiet_hours(cfg, datetime(2026, 9, 24, 1, 0, tzinfo=UTC), tz)  # 06:00 PKT
    assert not in_quiet_hours(cfg, datetime(2026, 9, 24, 3, 0, tzinfo=UTC), tz)  # 08:00 PKT


def test_settings_validation():
    with pytest.raises(ValueError, match="email needs"):
        Notifications(email_enabled=True)
    with pytest.raises(ValueError):
        Notifications(smtp_host="bad host; rm -rf")
    with pytest.raises(ValueError, match="cron"):
        Schedules(morning_scan="every day at 7")
    with pytest.raises(ValueError, match="time zone"):
        Schedules(timezone="Asia/Nowhere")
