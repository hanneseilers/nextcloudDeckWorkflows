"""Shared SMTP config loading/sending - used by both the send_email action
module and main.py's failure-notification emails, so there's exactly one
place that knows how to read config/smtp.yaml and open an SMTP connection."""

from __future__ import annotations

import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Optional

import yaml

from automation.config.settings import REPO_ROOT

SMTP_CONFIG_PATH = REPO_ROOT / "config" / "smtp.yaml"


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: Optional[str]
    password: Optional[str]
    use_tls: bool
    from_address: str


def load_smtp_config() -> SmtpConfig:
    if not SMTP_CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing {SMTP_CONFIG_PATH} (copy config/smtp.example.yaml and fill in your values)"
        )
    data = yaml.safe_load(SMTP_CONFIG_PATH.read_text()) or {}
    return SmtpConfig(
        host=data["host"],
        port=int(data.get("port", 587)),
        username=data.get("username"),
        password=data.get("password"),
        use_tls=bool(data.get("use_tls", True)),
        from_address=data.get("from_address") or data.get("username"),
    )


_RECIPIENT_SEPARATORS = re.compile(r"[,;\n]")


def parse_recipients(value: Any) -> list[str]:
    """One address, several separated by comma/semicolon/newline, or a list
    -> the addresses in order, trimmed, without duplicates (compared
    case-insensitively). Plain addresses only - "Name <a@b.c>" isn't
    supported (a comma in a display name would split it). An entry without
    an "@" raises ValueError, so a typo fails the step instead of a vague SMTP error."""

    if isinstance(value, str):
        parts = _RECIPIENT_SEPARATORS.split(value)
    elif isinstance(value, (list, tuple)):
        parts = [piece for item in value if isinstance(item, str) for piece in _RECIPIENT_SEPARATORS.split(item)]
    else:
        parts = []
    addresses: list[str] = []
    for part in parts:
        address = part.strip()
        if not address:
            continue
        if "@" not in address or any(ch.isspace() for ch in address):
            raise ValueError(f"Invalid email address: {address!r}")
        if address.lower() not in (known.lower() for known in addresses):
            addresses.append(address)
    return addresses


def send_email(smtp_config: SmtpConfig, *, to: Any, subject: str, body: str) -> list[str]:
    """Sends one message to every address in `to` (see parse_recipients).
    Returns the addresses the server refused - a partly refused message
    still goes out to the others, so that is not an exception here."""

    recipients = parse_recipients(to)
    if not recipients:
        raise ValueError("No recipient given")
    message = EmailMessage()
    message["From"] = smtp_config.from_address
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(smtp_config.host, smtp_config.port, timeout=15) as client:
        if smtp_config.use_tls:
            client.starttls()
        if smtp_config.username:
            client.login(smtp_config.username, smtp_config.password or "")
        refused = client.send_message(message)
    return sorted(refused) if isinstance(refused, dict) else []
