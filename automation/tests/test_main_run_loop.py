from __future__ import annotations

import logging
import sqlite3

from automation.adapters.persistence.sqlite_state_store import SqliteStateStore
from automation.adapters.persistence.yaml_workflow_repository import YamlWorkflowRepository
from automation.config.settings import NextcloudInstanceConfig, Settings
from automation.core.domain.models import ActionStep, EventType, Trigger, Workflow
from automation.main import run


class FakeResponse:
    def __init__(self, json_data) -> None:
        self.status_code = 200
        self.ok = True
        self._json = json_data
        self.content = b"x"
        self.text = ""

    def json(self):
        return self._json


def make_instances() -> dict[str, NextcloudInstanceConfig]:
    return {
        "prod": NextcloudInstanceConfig(
            name="prod", base_url="https://cloud.example.com", username="bot", app_password="secret"
        )
    }


def fake_requests_for(state: dict) -> callable:
    """A stateful fake for requests.Session.request: GET .../stacks reflects
    state["stack_id"], PUT .../reorder updates it - so a real move_card
    action visibly changes what the next poll sees, the same way a real
    Nextcloud would. NextcloudClient makes its calls through a
    requests.Session instance, so the patched method is called bound (the
    session instance is the leading arg, unused here)."""

    def fake_request(self, method, url, **kwargs):
        if method == "GET" and url.endswith("/stacks"):
            card = {"id": 1, "title": "Card", "lastModified": 1}
            stacks = [
                {"id": 10, "cards": [card] if state["stack_id"] == 10 else []},
                {"id": 20, "cards": [card] if state["stack_id"] == 20 else []},
            ]
            return FakeResponse(stacks)
        if method == "PUT" and "/reorder" in url:
            state["stack_id"] = kwargs["json"]["stackId"]
            return FakeResponse(None)
        return FakeResponse([])

    return fake_request


def test_run_reprocesses_within_one_invocation_when_an_action_triggers_another_workflow(tmp_path, monkeypatch):
    state = {"stack_id": 10}
    monkeypatch.setattr("requests.Session.request", fake_requests_for(state))

    workflows_dir = tmp_path / "workflows"
    workflows = YamlWorkflowRepository(workflows_dir)
    workflows.save(Workflow(
        id="w1", name="W1", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_CREATED, stack_id=10),
        actions=(ActionStep(module="move_card", params={"target_stack_id": 20}),),
    ))
    workflows.save(Workflow(
        id="w2", name="W2", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_MOVED, stack_id=20),
        actions=(ActionStep(module="log_action", params={"message": "w2 ran"}),),
    ))

    settings = Settings(
        workflows_dir=workflows_dir,
        state_db_path=tmp_path / "state.sqlite3",
        log_level="INFO",
        instances=make_instances(),
        max_run_seconds=30.0,
    )

    run(settings)

    # w1 moved the card for real (via the fake Deck API's stateful reorder).
    assert state["stack_id"] == 20

    with sqlite3.connect(settings.state_db_path) as conn:
        workflow_ids = {row[0] for row in conn.execute("SELECT workflow_id FROM execution_log")}
    # w2 only ran because w1's move was detected and acted on within this
    # same run() call - without the fixed-point loop it would need a second
    # cron invocation.
    assert workflow_ids == {"w1", "w2"}


def test_run_stops_at_max_run_seconds_instead_of_looping_forever(tmp_path, monkeypatch, caplog):
    state = {"stack_id": 10}
    monkeypatch.setattr("requests.Session.request", fake_requests_for(state))

    workflows_dir = tmp_path / "workflows"
    workflows = YamlWorkflowRepository(workflows_dir)
    workflows.save(Workflow(
        id="kickoff", name="kickoff", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_CREATED, stack_id=10),
        actions=(ActionStep(module="move_card", params={"target_stack_id": 20}),),
    ))
    workflows.save(Workflow(
        id="ping", name="ping", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_MOVED, stack_id=20),
        actions=(ActionStep(module="move_card", params={"target_stack_id": 10}),),
    ))
    workflows.save(Workflow(
        id="pong", name="pong", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_MOVED, stack_id=10),
        actions=(ActionStep(module="move_card", params={"target_stack_id": 20}),),
    ))

    settings = Settings(
        workflows_dir=workflows_dir,
        state_db_path=tmp_path / "state.sqlite3",
        log_level="INFO",
        instances=make_instances(),
        max_run_seconds=0.05,
    )

    caplog.set_level(logging.WARNING, logger="automation.main")

    run(settings)  # must return promptly - ping/pong would bounce forever otherwise

    assert any("max_run_seconds" in record.message for record in caplog.records)


def test_run_processes_a_queued_test_run_even_for_a_disabled_workflow(tmp_path, monkeypatch):
    state = {"stack_id": 10}
    monkeypatch.setattr("requests.Session.request", fake_requests_for(state))

    workflows_dir = tmp_path / "workflows"
    workflows = YamlWorkflowRepository(workflows_dir)
    workflows.save(Workflow(
        id="disabled-wf", name="Disabled", instance="prod", board_id=1, enabled=False,
        trigger=Trigger(event_type=EventType.CARD_MOVED, stack_id=99),  # would never match a real event here
        actions=(ActionStep(module="log_action", params={"message": "test run worked"}),),
    ))

    settings = Settings(
        workflows_dir=workflows_dir,
        state_db_path=tmp_path / "state.sqlite3",
        log_level="INFO",
        instances=make_instances(),
        max_run_seconds=5.0,
    )
    state_store = SqliteStateStore(settings.state_db_path)
    test_run_id = state_store.enqueue_test_run("disabled-wf", card_id=1)

    run(settings)

    fetched = state_store.get_test_run(test_run_id)
    assert fetched["status"] == "done"
    assert fetched["run_id"]

    with sqlite3.connect(settings.state_db_path) as conn:
        rows = conn.execute(
            "SELECT workflow_id, module, success FROM execution_log WHERE run_id = ?", (fetched["run_id"],)
        ).fetchall()
    assert rows == [("disabled-wf", "log_action", 1)]


def test_run_marks_a_test_run_for_an_unknown_card_as_error(tmp_path, monkeypatch):
    state = {"stack_id": 10}
    monkeypatch.setattr("requests.Session.request", fake_requests_for(state))

    workflows_dir = tmp_path / "workflows"
    workflows = YamlWorkflowRepository(workflows_dir)
    workflows.save(Workflow(
        id="wf-1", name="WF1", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_CREATED, stack_id=10),
        actions=(ActionStep(module="log_action", params={"message": "hi"}),),
    ))

    settings = Settings(
        workflows_dir=workflows_dir,
        state_db_path=tmp_path / "state.sqlite3",
        log_level="INFO",
        instances=make_instances(),
        max_run_seconds=5.0,
    )
    state_store = SqliteStateStore(settings.state_db_path)
    test_run_id = state_store.enqueue_test_run("wf-1", card_id=999999)  # doesn't exist on the fake board

    run(settings)

    fetched = state_store.get_test_run(test_run_id)
    assert fetched["status"] == "error"
    assert "999999" in fetched["error"]
