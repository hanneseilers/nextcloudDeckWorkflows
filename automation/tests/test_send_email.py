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


def test_the_same_change_is_deduped_but_a_new_change_on_the_card_sends_again(tmp_path, monkeypatch, smtp_client, context):
    from dataclasses import replace

    write_smtp_config(tmp_path, monkeypatch)
    _with_guard(context)
    params = {"to": "alice@example.com", "subject": "Hi", "body": "Hello"}
    context.event = replace(context.event, previous_last_modified=100)

    SendEmailAction().execute(context, params)
    SendEmailAction().execute(context, params)  # the same event again (a repeated, killed run)
    context.event = replace(context.event, previous_last_modified=200)  # the card changed again: new event
    SendEmailAction().execute(context, params)

    assert smtp_client.send_message.call_count == 2


def test_only_event_triggered_runs_use_the_guard():
    from automation.core.domain.engine import WorkflowEngine
    from automation.core.domain.models import ActionStep, EventType, Trigger, Workflow
    from automation.testing.fakes import InMemoryDuplicateGuard, InMemoryExecutionLog, InMemoryWorkflowRepository

    seen = []

    class Probe:
        ACTION_NAME = "probe"

        def execute(self, ctx, params):
            seen.append(ctx.dedupe_store is not None)
            return {}

    wf = Workflow(id="w", name="w", instance="test", board_id=1, trigger=Trigger(event_type=EventType.CARD_CREATED),
                  actions=(ActionStep(module="probe"),))
    engine = WorkflowEngine(workflows=InMemoryWorkflowRepository([wf]), actions=InMemoryActionRegistry({"probe": Probe()}),
                            execution_log=InMemoryExecutionLog(), dedupe_store=InMemoryDuplicateGuard())
    event = DeckEvent(instance="test", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10)
    engine.handle(event, InMemoryDeckGateway())
    engine.run_single(wf, event, InMemoryDeckGateway())  # test run / schedule

    assert seen == [True, False]


# -- several recipients -----------------------------------------------------------

@pytest.mark.parametrize("to", [
    "anna@example.com, bernd@example.com",
    "anna@example.com;bernd@example.com",
    "anna@example.com\nbernd@example.com",
    ["anna@example.com", "bernd@example.com"],
    ["anna@example.com", " BERND@example.com", "Anna@Example.com"],  # duplicate (any case) removed
])
def test_one_mail_goes_to_all_recipients(tmp_path, monkeypatch, smtp_client, context, to):
    write_smtp_config(tmp_path, monkeypatch)
    smtp_client.send_message.return_value = {}

    out = SendEmailAction().execute(context, {"to": to, "subject": "S", "body": "B"})

    assert out == {"sent": True}
    smtp_client.send_message.assert_called_once()
    sent = smtp_client.send_message.call_args[0][0]
    assert [a.strip().lower() for a in sent["To"].split(",")] == ["anna@example.com", "bernd@example.com"]


def test_the_real_smtp_envelope_contains_every_recipient(tmp_path, monkeypatch, context):
    """Not mocked: a tiny SMTP server records the RCPT TO lines smtplib really sends."""

    import socketserver
    import threading

    rcpt, bodies = [], []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            say = lambda text: (self.wfile.write((text + "\r\n").encode()), self.wfile.flush())
            say("220 test")
            data, lines = False, []
            for raw in self.rfile:
                line = raw.decode().rstrip("\r\n")
                if data:
                    if line == ".":
                        bodies.append("\n".join(lines)); data = False; say("250 ok")
                    else:
                        lines.append(line)
                    continue
                upper = line.upper()
                if upper.startswith("RCPT TO"):
                    rcpt.append(line.split(":", 1)[1].strip(" <>"))
                if upper.startswith("DATA"):
                    data = True; say("354 go")
                elif upper.startswith("QUIT"):
                    say("221 bye"); return
                else:
                    say("250 ok")

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        write_smtp_config(tmp_path, monkeypatch, host="127.0.0.1", port=server.server_address[1],
                          use_tls=False, username=None, password=None)
        SendEmailAction().execute(context, {"to": "anna@example.com; bernd@example.com", "subject": "S", "body": "B"})
    finally:
        server.shutdown()
    assert rcpt == ["anna@example.com", "bernd@example.com"]
    assert len(bodies) == 1  # one mail, not one per recipient


def test_a_refused_recipient_fails_the_step_but_the_others_got_the_mail(tmp_path, monkeypatch, smtp_client, context):
    write_smtp_config(tmp_path, monkeypatch)
    smtp_client.send_message.return_value = {"bernd@example.com": (550, b"no such user")}

    with pytest.raises(RuntimeError, match=r"refused.*bernd@example.com.*everybody else received"):
        SendEmailAction().execute(context, {"to": "anna@example.com, bernd@example.com", "subject": "S", "body": "B"})
    smtp_client.send_message.assert_called_once()


def test_a_typo_in_one_address_fails_before_anything_is_sent(tmp_path, monkeypatch, smtp_client, context):
    write_smtp_config(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="bernd"):
        SendEmailAction().execute(context, {"to": "anna@example.com, bernd-example.com", "subject": "S", "body": "B"})
    smtp_client.send_message.assert_not_called()


def test_no_recipient_at_all_fails_clearly(tmp_path, monkeypatch, smtp_client, context):
    write_smtp_config(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="no recipient"):
        SendEmailAction().execute(context, {"to": " , ; ", "subject": "S", "body": "B"})


def test_the_duplicate_guard_treats_a_list_and_the_same_text_alike(tmp_path, monkeypatch, smtp_client, context):
    write_smtp_config(tmp_path, monkeypatch)
    seen = set()

    class Guard:
        def seen_within(self, key, minutes):
            return key in seen

        def remember(self, key):
            seen.add(key)

    context.dedupe_store = Guard()
    SendEmailAction().execute(context, {"to": ["a@x.de", "b@x.de"], "subject": "S", "body": "B"})
    out = SendEmailAction().execute(context, {"to": "a@x.de, b@x.de", "subject": "S", "body": "B"})
    assert out == {"sent": False} and smtp_client.send_message.call_count == 1
