from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from string import Template
from typing import Any, ClassVar, Optional

import yaml

from automation.adapters.actions.base import WorkflowAction
from automation.config.settings import REPO_ROOT
from automation.core.ports.action_module import ActionContext

SMTP_CONFIG_PATH = REPO_ROOT / "config" / "smtp.yaml"
TEMPLATES_DIR = REPO_ROOT / "config" / "email_templates"


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: Optional[str]
    password: Optional[str]
    use_tls: bool
    from_address: str


def _load_smtp_config() -> SmtpConfig:
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


def _load_template(name: str) -> tuple[Optional[str], str]:
    """Loads config/email_templates/<name>.txt. The optional first line
    `Subject: ...` followed by a blank line sets the subject; everything after
    is the body. Returns (subject_or_None, body)."""

    path = TEMPLATES_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Unknown email template '{name}' (expected {path})")
    text = path.read_text()
    header, separator, rest = text.partition("\n\n")
    if separator and header.startswith("Subject:"):
        return header[len("Subject:"):].strip(), rest
    return None, text


class SendEmailAction(WorkflowAction):
    """Sends an email via SMTP.

    Server settings come from config/smtp.yaml (module-specific, gitignored -
    copy config/smtp.example.yaml). The subject/body are either given directly
    or loaded from a template file in config/email_templates/<name>.txt. Either
    way, $placeholder values from params['template_data'] are substituted with
    string.Template.safe_substitute - unresolved placeholders are left as-is
    instead of raising, so a template ahead of its data never breaks the send.
    Exact placeholder names are defined per template/workflow, not by this code.

    params:
      to: str - recipient address
      template: str (optional) - name of a file in config/email_templates/
      subject, body: str (optional) - used instead of `template`
      template_data: dict (optional) - values substituted into subject/body
    """

    ACTION_NAME: ClassVar[str] = "send_email"

    def execute(self, context: ActionContext, params: dict[str, Any]) -> None:
        template_data = params.get("template_data", {})

        if params.get("template"):
            subject, body = _load_template(params["template"])
            subject = params.get("subject", subject) or ""
        else:
            subject = params["subject"]
            body = params["body"]

        subject = Template(subject).safe_substitute(**template_data)
        body = Template(body).safe_substitute(**template_data)

        smtp_config = _load_smtp_config()
        message = EmailMessage()
        message["From"] = smtp_config.from_address
        message["To"] = params["to"]
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(smtp_config.host, smtp_config.port, timeout=15) as client:
            if smtp_config.use_tls:
                client.starttls()
            if smtp_config.username:
                client.login(smtp_config.username, smtp_config.password or "")
            client.send_message(message)
