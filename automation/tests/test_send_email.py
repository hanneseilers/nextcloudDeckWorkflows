from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import yaml

from automation.actions_registry import send_email as send_email_module
from automation.actions_registry.send_email import SendEmailAction
from automation.adapters import smtp_config as smtp_config_module
from automation.core.domain.models import DeckEvent, EventType
from automation.core.ports.action_module import ActionContext
from automation.testing.fakes import InMemoryActionRegistry, InMemoryDeckGateway


@pytest.fixture
def context() -> ActionContext:
    return ActionContext(
        event=DeckEvent(instance="test", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10),
        deck=InMemoryDeckGateway(),
        modules=InMemoryActionRegistry({}),
    )


@pytest.fixture
def smtp_client(monkeypatch):
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    smtp_cls = MagicMock(return_value=client)
    monkeypatch.setattr(smtp_config_module.smtplib, "SMTP", smtp_cls)
    return client


def write_smtp_config(tmp_path, monkeypatch, **overrides):
    config_path = tmp_path / "smtp.yaml"
    data = {
        "host": "smtp.example.com",
        "port": 587,
        "username": "bot@example.com",
        "password": "secret",
        "use_tls": True,
        "from_address": "bot@example.com",
    }
    data.update(overrides)
    config_path.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(smtp_config_module, "SMTP_CONFIG_PATH", config_path)
    return config_path


def test_send_email_with_direct_subject_and_body(tmp_path, monkeypatch, smtp_client, context):
    write_smtp_config(tmp_path, monkeypatch)

    SendEmailAction().execute(
        context,
        {"to": "alice@example.com", "subject": "Hi $name", "body": "Card update for $name", "template_data": {"name": "Alice"}},
    )

    sent = smtp_client.send_message.call_args[0][0]
    assert sent["To"] == "alice@example.com"
    assert sent["Subject"] == "Hi Alice"
    assert sent.get_content().strip() == "Card update for Alice"


def test_unresolved_placeholders_are_left_as_is(tmp_path, monkeypatch, smtp_client, context):
    write_smtp_config(tmp_path, monkeypatch)

    SendEmailAction().execute(
        context,
        {"to": "alice@example.com", "subject": "Hi $name", "body": "See $unset_placeholder"},
    )

    sent = smtp_client.send_message.call_args[0][0]
    assert sent["Subject"] == "Hi $name"
    assert sent.get_content().strip() == "See $unset_placeholder"


def test_global_variables_are_available_as_placeholders(tmp_path, monkeypatch, smtp_client, context):
    write_smtp_config(tmp_path, monkeypatch)
    context.variables["name"] = "Bob"

    SendEmailAction().execute(
        context,
        {"to": "alice@example.com", "subject": "Hi $name", "body": "Hi $name"},
    )

    sent = smtp_client.send_message.call_args[0][0]
    assert sent["Subject"] == "Hi Bob"
    assert sent.get_content().strip() == "Hi Bob"


def test_template_data_wins_over_a_same_named_global_variable(tmp_path, monkeypatch, smtp_client, context):
    write_smtp_config(tmp_path, monkeypatch)
    context.variables["name"] = "Bob"

    SendEmailAction().execute(
        context,
        {"to": "alice@example.com", "subject": "Hi $name", "body": "Hi $name", "template_data": {"name": "Alice"}},
    )

    sent = smtp_client.send_message.call_args[0][0]
    assert sent["Subject"] == "Hi Alice"


def test_send_email_from_a_template(tmp_path, monkeypatch, smtp_client, context):
    write_smtp_config(tmp_path, monkeypatch)
    templates_dir = tmp_path / "email_templates"
    templates_dir.mkdir()
    (templates_dir / "greeting.txt").write_text("Subject: Hello $name\n\nWelcome, $name!\n")
    monkeypatch.setattr(send_email_module, "TEMPLATES_DIR", templates_dir)

    SendEmailAction().execute(
        context,
        {"to": "alice@example.com", "template": "greeting", "template_data": {"name": "Alice"}},
    )

    sent = smtp_client.send_message.call_args[0][0]
    assert sent["Subject"] == "Hello Alice"
    assert sent.get_content().strip() == "Welcome, Alice!"


def test_missing_smtp_config_raises_a_clear_error(monkeypatch, tmp_path, context):
    monkeypatch.setattr(smtp_config_module, "SMTP_CONFIG_PATH", tmp_path / "does-not-exist.yaml")

    with pytest.raises(FileNotFoundError):
        SendEmailAction().execute(context, {"to": "alice@example.com", "subject": "Hi", "body": "Hi"})


def test_missing_template_raises_a_clear_error(tmp_path, monkeypatch, context):
    write_smtp_config(tmp_path, monkeypatch)
    monkeypatch.setattr(send_email_module, "TEMPLATES_DIR", tmp_path / "email_templates")

    with pytest.raises(FileNotFoundError):
        SendEmailAction().execute(context, {"to": "alice@example.com", "template": "does-not-exist"})


def test_tls_and_login_are_used_when_configured(tmp_path, monkeypatch, smtp_client, context):
    write_smtp_config(tmp_path, monkeypatch, use_tls=True, username="bot@example.com", password="secret")

    SendEmailAction().execute(context, {"to": "alice@example.com", "subject": "Hi", "body": "Hi"})

    smtp_client.starttls.assert_called_once()
    smtp_client.login.assert_called_once_with("bot@example.com", "secret")


def test_no_login_when_no_username_configured(tmp_path, monkeypatch, smtp_client, context):
    write_smtp_config(tmp_path, monkeypatch, use_tls=False, username=None, password=None)

    SendEmailAction().execute(context, {"to": "alice@example.com", "subject": "Hi", "body": "Hi"})

    smtp_client.starttls.assert_not_called()
    smtp_client.login.assert_not_called()


def _with_guard(context, workflow_id="wf"):
    from automation.testing.fakes import InMemoryDuplicateGuard

    context.dedupe_store = InMemoryDuplicateGuard()
    context.workflow_id = workflow_id
    return context


def test_an_identical_email_is_not_sent_twice_within_the_window(tmp_path, monkeypatch, smtp_client, context):
    write_smtp_config(tmp_path, monkeypatch)
    _with_guard(context)
    params = {"to": "alice@example.com", "subject": "Hi", "body": "Hello"}

    first = SendEmailAction().execute(context, params)
    second = SendEmailAction().execute(context, params)

    assert (first, second) == ({"sent": True}, {"sent": False})
    assert smtp_client.send_message.call_count == 1


def test_a_different_recipient_subject_body_card_or_workflow_is_not_a_duplicate(tmp_path, monkeypatch, smtp_client, context):
    write_smtp_config(tmp_path, monkeypatch)
    _with_guard(context)
    base = {"to": "alice@example.com", "subject": "Hi", "body": "Hello"}

    SendEmailAction().execute(context, base)
    SendEmailAction().execute(context, {**base, "to": "bob@example.com"})
    SendEmailAction().execute(context, {**base, "subject": "Other"})
    SendEmailAction().execute(context, {**base, "body": "Other"})
    context.workflow_id = "another-workflow"
    SendEmailAction().execute(context, base)

    assert smtp_client.send_message.call_count == 5


def test_dedupe_minutes_zero_turns_the_protection_off(tmp_path, monkeypatch, smtp_client, context):
    write_smtp_config(tmp_path, monkeypatch)
    _with_guard(context)
    params = {"to": "alice@example.com", "subject": "Hi", "body": "Hello", "dedupe_minutes": 0}

    SendEmailAction().execute(context, params)
    SendEmailAction().execute(context, params)

    assert smtp_client.send_message.call_count == 2


def test_a_failed_send_is_not_remembered_so_it_can_be_retried(tmp_path, monkeypatch, smtp_client, context):
    write_smtp_config(tmp_path, monkeypatch)
    _with_guard(context)
    params = {"to": "alice@example.com", "subject": "Hi", "body": "Hello"}
    smtp_client.send_message.side_effect = [RuntimeError("smtp down"), None]

    with pytest.raises(RuntimeError):
        SendEmailAction().execute(context, params)
    assert SendEmailAction().execute(context, params) == {"sent": True}
