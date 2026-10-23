from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from string import Template
from typing import Any, ClassVar, Optional

from automation.adapters.actions.base import WorkflowAction
from automation.adapters.smtp_config import load_smtp_config, send_email as smtp_send
from automation.config.settings import REPO_ROOT
from automation.core.ports.action_module import ActionContext

logger = logging.getLogger(__name__)

DEFAULT_DEDUPE_MINUTES = 10080  # 7 days - long enough for any cron restart

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
      dedupe_minutes: number (optional, default 10080 = 7 days) - when a run
        is killed right after sending and the next run repeats the same event,
        the identical email (same workflow, card, triggering change,
        recipient, subject and body) is not sent again within this many
        minutes; 0 turns this off. "Same triggering change" means the card's
        state before the event, so a new event on the card (moved again,
        edited again) sends normally. Only event-triggered runs use it - test
        runs, schedules and one-time links always send.

    output:
      sent: bool - false if the email was skipped as a recent duplicate
    """

    ACTION_NAME: ClassVar[str] = "send_email"
    LABEL: ClassVar[str] = "E-Mail senden"

    def default_input(self) -> dict[str, Any]:
        return {
            "to": "", "subject": "", "body": "", "template": None, "template_data": {},
            "dedupe_minutes": DEFAULT_DEDUPE_MINUTES,
        }

    def default_output(self) -> dict[str, Any]:
        return {"sent": True}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        template_data = {**context.variables, **params.get("template_data", {})}

        if params.get("template"):
            subject, body = _load_template(params["template"])
            # An explicit, non-empty `subject` param overrides the
            # template's own `Subject:` header; a missing OR blank one
            # (the website's builder always sends an empty-string default
            # for every send_email step, template-based or not) falls back
            # to the template's subject instead of silently sending blank.
            subject = params.get("subject") or subject or ""
        else:
            subject = params["subject"]
            body = params["body"]

        subject = Template(subject).safe_substitute(**template_data)
        body = Template(body).safe_substitute(**template_data)

        raw_minutes = params.get("dedupe_minutes")
        minutes = DEFAULT_DEDUPE_MINUTES if raw_minutes is None else float(raw_minutes)
        guard = context.dedupe_store if minutes > 0 else None
        key = None
        if guard is not None:
            key = "email:" + hashlib.sha256(json.dumps(
                [
                    context.workflow_id, context.event.card_id, context.event.event_type.value,
                    context.event.previous_last_modified, params["to"], subject, body,
                ]
            ).encode()).hexdigest()
            if guard.seen_within(key, minutes):
                logger.warning(
                    "Not sending to %s: an identical email went out less than %g minutes ago "
                    "(workflow '%s', card %s)", params["to"], minutes, context.workflow_id, context.event.card_id,
                )
                return {"sent": False}

        smtp_send(load_smtp_config(), to=params["to"], subject=subject, body=body)
        if guard is not None:
            guard.remember(key)  # after the send: a kill in between sends again rather than losing the mail
        return {"sent": True}
