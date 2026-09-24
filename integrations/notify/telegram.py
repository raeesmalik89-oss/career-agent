"""Telegram Bot API sendMessage (plain text, no link previews). The bot token is part of the URL, so every error
text is scrubbed of it before it leaves this module."""

import json
import urllib.error
import urllib.request

from integrations.notify import DeliveryError, Message, scrub

API = "https://api.telegram.org"
MAX_CHARS = 4000  # Telegram's limit is 4096


def send(token: str, chat_id: str, msg: Message, timeout: float = 20) -> None:
    payload = json.dumps({"chat_id": chat_id, "text": msg.plain(MAX_CHARS), "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(  # noqa: S310 - fixed https host
        f"{API}/bot{token}/sendMessage", data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = json.loads(resp.read(65536) or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read(4096)).get("description", "")
        except (ValueError, OSError):
            detail = ""
        raise DeliveryError(scrub(f"Telegram HTTP {exc.code}: {detail}", token)) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise DeliveryError(scrub(f"{type(exc).__name__}: {exc}", token)) from None
    if not body.get("ok"):
        raise DeliveryError(scrub(f"Telegram refused the message: {body.get('description', 'unknown error')}", token))
