"""Plain-text email over SMTP. TLS is mandatory: port 465 uses implicit TLS, any other port must offer STARTTLS."""

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from integrations.notify import DeliveryError, Message, scrub


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: str | None
    password: str | None
    sender: str
    to: str


def _one_line(s: str) -> str:
    return " ".join(s.split())[:200]


def build(cfg: SmtpConfig, msg: Message) -> EmailMessage:
    em = EmailMessage()
    em["Subject"] = f"[Career Agent] {_one_line(msg.title)}"
    em["From"] = cfg.sender
    em["To"] = cfg.to
    em["Date"] = formatdate(localtime=True)
    em["Message-ID"] = make_msgid(domain=cfg.sender.rsplit("@", 1)[-1])
    em.set_content(msg.plain())
    return em


def send(cfg: SmtpConfig, msg: Message, timeout: float = 20) -> None:
    em = build(cfg, msg)
    ctx = ssl.create_default_context()
    try:
        if cfg.port == 465:
            server: smtplib.SMTP = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=timeout, context=ctx)
        else:
            server = smtplib.SMTP(cfg.host, cfg.port, timeout=timeout)
        with server:
            if cfg.port != 465:
                server.ehlo()
                if not server.has_extn("starttls"):
                    raise DeliveryError("the SMTP server does not offer STARTTLS; refusing to send without TLS")
                server.starttls(context=ctx)
                server.ehlo()
            if cfg.username and cfg.password:
                server.login(cfg.username, cfg.password)
            server.send_message(em)
    except DeliveryError:
        raise
    except (smtplib.SMTPException, OSError) as exc:
        raise DeliveryError(scrub(f"{type(exc).__name__}: {exc}", cfg.password)) from None
