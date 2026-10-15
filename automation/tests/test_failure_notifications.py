from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import yaml

from automation.adapters import smtp_config as smtp_config_module
from automation.adapters.persistence.sqlite_state_store import SqliteStateStore
from automation.adapters.persistence.yaml_workflow_repository import YamlWorkflowRepository
from automation.config.settings import ErrorNotificationConfig, NextcloudInstanceConfig, Settings
from automation.core.domain.models import ActionResult, DeckEvent, EventType, ExecutionResult, Trigger, Workflow
from automation.main import _process_failure_notifications


def make_settings(tmp_path, threshold=3, enabled=True) -> Settings:
    return Settings(
        workflows_dir=tmp_path / "workflows",
        state_db_path=tmp_path / "state.sqlite3",
        log_level="INFO",
        instances={"prod": NextcloudInstanceConfig(name="prod", base_url="https://x", username="u", app_password="p")},
        error_notifications=ErrorNotificationConfig(enabled=enabled, threshold=threshold, to="admin@example.com"),
    )


@pytest.fixture
def smtp_client(monkeypatch):
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    monkeypatch.setattr(smtp_config_module.smtplib, "SMTP", MagicMock(return_value=client))
    return client


def write_smtp_config(tmp_path, monkeypatch):
    config_path = tmp_path / "smtp.yaml"
    config_path.write_text(yaml.safe_dump({
        "host": "smtp.example.com", "port": 587, "username": None, "password": None,
        "use_tls": False, "from_address": "bot@example.com",
    }))
    monkeypatch.setattr(smtp_config_module, "SMTP_CONFIG_PATH", config_path)


def record(store: SqliteStateStore, workflow_id: str, success: bool) -> None:
    event = DeckEvent(instance="prod", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10)
    store.record(ExecutionResult(
        workflow_id=workflow_id, event=event,
        action_results=[ActionResult(module="a", success=success, error=None if success else "boom")],
    ))


def make_workflow(workflow_id: str) -> Workflow:
    return Workflow(
        id=workflow_id, name="Flaky workflow", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_CREATED), actions=(),
    )


def test_sends_a_notification_once_the_threshold_is_crossed(tmp_path, monkeypatch, smtp_client):
    write_smtp_config(tmp_path, monkeypatch)
    settings = make_settings(tmp_path, threshold=3)
    workflows = YamlWorkflowRepository(settings.workflows_dir)
    workflows.save(make_workflow("flaky"))
    state_store = SqliteStateStore(settings.state_db_path)
    for _ in range(3):
        record(state_store, "flaky", success=False)

    _process_failure_notifications(settings, workflows, state_store)

    smtp_client.send_message.assert_called_once()
    sent = smtp_client.send_message.call_args[0][0]
    assert sent["To"] == "admin@example.com"
    assert "flaky" in sent.get_content()


def test_does_not_notify_before_the_threshold_is_reached(tmp_path, monkeypatch, smtp_client):
    write_smtp_config(tmp_path, monkeypatch)
    settings = make_settings(tmp_path, threshold=3)
    workflows = YamlWorkflowRepository(settings.workflows_dir)
    workflows.save(make_workflow("flaky"))
    state_store = SqliteStateStore(settings.state_db_path)
    record(state_store, "flaky", success=False)
    record(state_store, "flaky", success=False)  # only 2 failures - threshold is 3

    _process_failure_notifications(settings, workflows, state_store)

    smtp_client.send_message.assert_not_called()


def test_does_not_notify_twice_for_the_same_streak(tmp_path, monkeypatch, smtp_client):
    write_smtp_config(tmp_path, monkeypatch)
    settings = make_settings(tmp_path, threshold=3)
    workflows = YamlWorkflowRepository(settings.workflows_dir)
    workflows.save(make_workflow("flaky"))
    state_store = SqliteStateStore(settings.state_db_path)
    for _ in range(3):
        record(state_store, "flaky", success=False)

    _process_failure_notifications(settings, workflows, state_store)
    record(state_store, "flaky", success=False)  # a 4th failure, same ongoing streak
    _process_failure_notifications(settings, workflows, state_store)

    smtp_client.send_message.assert_called_once()


def test_notifies_again_after_recovering_and_failing_again(tmp_path, monkeypatch, smtp_client):
    write_smtp_config(tmp_path, monkeypatch)
    settings = make_settings(tmp_path, threshold=3)
    workflows = YamlWorkflowRepository(settings.workflows_dir)
    workflows.save(make_workflow("flaky"))
    state_store = SqliteStateStore(settings.state_db_path)
    for _ in range(3):
        record(state_store, "flaky", success=False)
    _process_failure_notifications(settings, workflows, state_store)

    record(state_store, "flaky", success=True)  # recovered
    _process_failure_notifications(settings, workflows, state_store)

    for _ in range(3):
        record(state_store, "flaky", success=False)
    _process_failure_notifications(settings, workflows, state_store)

    assert smtp_client.send_message.call_count == 2


def test_disabled_by_default_configuration(tmp_path, monkeypatch, smtp_client):
    write_smtp_config(tmp_path, monkeypatch)
    settings = make_settings(tmp_path, threshold=3)
    settings = Settings(**{**settings.__dict__, "error_notifications": None})
    workflows = YamlWorkflowRepository(settings.workflows_dir)
    workflows.save(make_workflow("flaky"))
    state_store = SqliteStateStore(settings.state_db_path)
    for _ in range(5):
        record(state_store, "flaky", success=False)

    _process_failure_notifications(settings, workflows, state_store)

    smtp_client.send_message.assert_not_called()
