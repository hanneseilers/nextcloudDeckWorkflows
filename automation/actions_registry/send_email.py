from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any, ClassVar, Optional

from automation.adapters.actions.base import WorkflowAction
from automation.adapters.smtp_config import load_smtp_config, send_email as smtp_send
from automation.config.settings import REPO_ROOT
from automation.core.ports.action_module import ActionContext

TEMPLATES_DIR = REPO_ROOT / "config" / "email_templates"


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
    way, $placeholder values are substituted with string.Template.safe_substitute
    from context.variables (global, set via set_variable) merged with
    params['template_data'] (template_data wins on a name clash) - unresolved
    placeholders are left as-is instead of raising, so a template ahead of its
    data never breaks the send.

    params:
      to: str - recipient address
      template: str (optional) - name of a file in config/email_templates/
      subject, body: str (optional) - used instead of `template`
      template_data: dict (optional) - values substituted into subject/body
    """

    ACTION_NAME: ClassVar[str] = "send_email"

    def default_input(self) -> dict[str, Any]:
        return {"to": "", "subject": "", "body": "", "template": None, "template_data": {}}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        template_data = {**context.variables, **params.get("template_data", {})}

        if params.get("template"):
            subject, body = _load_template(params["template"])
            subject = params.get("subject", subject) or ""
        else:
            subject = params["subject"]
            body = params["body"]

        subject = Template(subject).safe_substitute(**template_data)
        body = Template(body).safe_substitute(**template_data)

        smtp_send(load_smtp_config(), to=params["to"], subject=subject, body=body)
        return {}
