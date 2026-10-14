"""Shared SMTP config loading/sending - used by both the send_email action
module and main.py's failure-notification emails, so there's exactly one
place that knows how to read config/smtp.yaml and open an SMTP connection."""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

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


def send_email(smtp_config: SmtpConfig, *, to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = smtp_config.from_address
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(smtp_config.host, smtp_config.port, timeout=15) as client:
        if smtp_config.use_tls:
            client.starttls()
        if smtp_config.username:
            client.login(smtp_config.username, smtp_config.password or "")
        client.send_message(message)
