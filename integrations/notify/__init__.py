"""Outbound notification channels. Each sender takes a Message and raises DeliveryError on failure.

Senders never log or return secrets: error texts are scrubbed before they are stored."""

from dataclasses import dataclass


class DeliveryError(Exception):
    pass


@dataclass(frozen=True)
class Message:
    title: str
    body: str
    url: str | None = None  # absolute dashboard link

    def plain(self, limit: int | None = None) -> str:
        text = self.title + ("\n\n" + self.body if self.body else "") + (f"\n\nOpen: {self.url}" if self.url else "")
        if limit and len(text) > limit:
            keep = limit - len("\n…(truncated)") - (len(self.url) + 8 if self.url else 0)
            text = text[: max(keep, 0)] + "\n…(truncated)" + (f"\nOpen: {self.url}" if self.url else "")
        return text


def scrub(text: str, *secrets: str | None) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text[:300]
