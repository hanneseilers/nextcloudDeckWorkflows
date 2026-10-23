from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from automation.adapters.persistence.sqlite_state_store import SqliteStateStore
from automation.adapters.persistence.yaml_workflow_repository import YamlWorkflowRepository
from automation.config.settings import NextcloudInstanceConfig, Settings, WebhookConfig
from automation.core.domain.models import ActionStep, EventType, ScheduleTrigger, Trigger, Workflow
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


def test_run_ends_a_ping_pong_between_columns_on_its_own(tmp_path, monkeypatch, caplog):
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
        max_run_seconds=5.0,
    )

    caplog.set_level(logging.INFO, logger="automation")
    run(settings)

    # Each workflow runs at most once per (card, column) per invocation, so
    # the bounce stops by itself instead of running into max_run_seconds.
    assert not any("max_run_seconds" in record.message for record in caplog.records)
    with sqlite3.connect(settings.state_db_path) as conn:
        ran = conn.execute(
            "SELECT workflow_id, COUNT(*) FROM execution_log GROUP BY workflow_id"
        ).fetchall()
    assert all(count == 1 for _, count in ran)


def test_run_does_not_retrigger_a_workflow_on_its_own_change(tmp_path, monkeypatch):
    state = {"title": "Card", "modified": 1, "puts": 0}

    def fake_request(self, method, url, **kwargs):
        card = {"id": 1, "title": state["title"], "lastModified": state["modified"]}
        if method == "GET" and url.endswith("/stacks"):
            return FakeResponse([{"id": 10, "cards": [card]}])
        if method == "GET" and "/cards/1" in url:
            return FakeResponse(card)
        if method == "PUT" and "/cards/1" in url:
            state["puts"] += 1
            state["title"] = kwargs["json"]["title"]
            state["modified"] += 1  # every write bumps lastModified, like Deck does
            return FakeResponse(card)
        return FakeResponse({})

    monkeypatch.setattr("requests.Session.request", fake_request)

    workflows_dir = tmp_path / "workflows"
    YamlWorkflowRepository(workflows_dir).save(Workflow(
        id="retitle", name="retitle", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_UPDATED),
        actions=(ActionStep(module="set_title", params={"title": "Neuer Titel"}),),
    ))
    settings = Settings(
        workflows_dir=workflows_dir, state_db_path=tmp_path / "state.sqlite3", log_level="INFO",
        instances=make_instances(), max_run_seconds=5.0,
    )

    run(settings)  # baseline: the card is new -> card_created, no card_updated workflow matches
    state["modified"] += 1  # someone else edits the card
    run(settings)

    assert state["puts"] == 1  # ran for the edit, but not again for its own change

    state["modified"] += 1  # a later, separate edit is a new event in a new run -> runs again
    run(settings)
    assert state["puts"] == 2


def test_run_stops_at_max_run_seconds_instead_of_looping_forever(tmp_path, monkeypatch, caplog):
    cards = [{"id": 1, "title": "Card", "lastModified": 1}]

    def fake_request(self, method, url, **kwargs):
        if method == "GET" and url.endswith("/stacks"):
            return FakeResponse([{"id": 10, "cards": list(cards)}])
        if method == "GET" and "/cards/" in url:
            return FakeResponse(cards[0])
        if method == "POST" and url.endswith("/stacks/10/cards"):
            new = {"id": len(cards) + 1, "title": kwargs["json"]["title"], "lastModified": 1}
            cards.append(new)  # every copy is a brand-new card -> a new card_created event, forever
            return FakeResponse(new)
        return FakeResponse({})

    monkeypatch.setattr("requests.Session.request", fake_request)

    workflows_dir = tmp_path / "workflows"
    YamlWorkflowRepository(workflows_dir).save(Workflow(
        id="breed", name="breed", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_CREATED, stack_id=10),
        actions=(ActionStep(module="copy_card", params={"target_board_id": 1, "target_stack_id": 10}),),
    ))
    settings = Settings(
        workflows_dir=workflows_dir, state_db_path=tmp_path / "state.sqlite3", log_level="INFO",
        instances=make_instances(), max_run_seconds=0.05,
    )

    caplog.set_level(logging.WARNING, logger="automation.main")

    run(settings)  # must return promptly - endlessly created cards would otherwise loop forever

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


def test_run_fires_a_due_schedule_triggered_workflow_exactly_once(tmp_path, monkeypatch):
    # The workflow's board_id still makes run() poll that board for Deck
    # events too (trigger type isn't filtered there) - fake the Deck API so
    # that poll doesn't make a real network call.
    monkeypatch.setattr("requests.Session.request", fake_requests_for({"stack_id": 10}))
    # Already in the past "today" by the time run() checks it, regardless of
    # when this test actually executes.
    scheduled_time = (datetime.now() - timedelta(minutes=1)).strftime("%H:%M")

    workflows_dir = tmp_path / "workflows"
    workflows = YamlWorkflowRepository(workflows_dir)
    workflows.save(Workflow(
        id="daily-digest", name="Daily digest", instance="prod", board_id=1,
        trigger=Trigger(schedule=ScheduleTrigger(time=scheduled_time)),
        actions=(ActionStep(module="log_action", params={"message": "good morning"}),),
    ))

    settings = Settings(
        workflows_dir=workflows_dir,
        state_db_path=tmp_path / "state.sqlite3",
        log_level="INFO",
        instances=make_instances(),
        max_run_seconds=5.0,
    )

    run(settings)

    with sqlite3.connect(settings.state_db_path) as conn:
        rows = conn.execute(
            "SELECT workflow_id, module, success FROM execution_log WHERE workflow_id = 'daily-digest'"
        ).fetchall()
    assert rows == [("daily-digest", "log_action", 1)]

    # A second run() within the same scheduled slot must NOT fire it again.
    run(settings)

    with sqlite3.connect(settings.state_db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM execution_log WHERE workflow_id = 'daily-digest'"
        ).fetchone()[0]
    assert count == 1


def test_run_records_a_clear_error_when_a_schedule_triggered_workflow_uses_a_card_action(tmp_path, monkeypatch):
    # The workflow's board_id still makes run() poll that board for Deck
    # events too (trigger type isn't filtered there) - fake the Deck API so
    # that poll doesn't make a real network call.
    monkeypatch.setattr("requests.Session.request", fake_requests_for({"stack_id": 10}))
    scheduled_time = (datetime.now() - timedelta(minutes=1)).strftime("%H:%M")

    workflows_dir = tmp_path / "workflows"
    workflows = YamlWorkflowRepository(workflows_dir)
    workflows.save(Workflow(
        id="bad-schedule", name="Bad schedule", instance="prod", board_id=1,
        trigger=Trigger(schedule=ScheduleTrigger(time=scheduled_time)),
        actions=(ActionStep(module="set_title", params={"title": "x"}),),
    ))

    settings = Settings(
        workflows_dir=workflows_dir,
        state_db_path=tmp_path / "state.sqlite3",
        log_level="INFO",
        instances=make_instances(),
        max_run_seconds=5.0,
    )

    run(settings)  # must not raise/crash the whole run

    with sqlite3.connect(settings.state_db_path) as conn:
        rows = conn.execute(
            "SELECT success, error FROM execution_log WHERE workflow_id = 'bad-schedule'"
        ).fetchall()
    assert rows[0][0] == 0
    assert "schedule-triggered" in rows[0][1]


def test_run_sets_a_heartbeat_on_successful_completion(tmp_path):
    settings = Settings(
        workflows_dir=tmp_path / "workflows",
        state_db_path=tmp_path / "state.sqlite3",
        log_level="INFO",
        instances=make_instances(),
        max_run_seconds=5.0,
    )

    run(settings)

    with sqlite3.connect(settings.state_db_path) as conn:
        row = conn.execute("SELECT last_run_at FROM heartbeat WHERE id = 1").fetchone()
    assert row is not None and row[0]


def test_webhooks_disabled_by_default_polls_every_run(tmp_path, monkeypatch):
    """Baseline: with no webhooks configured at all, behavior is exactly
    what it always was - every board is polled every single run()."""

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
        workflows_dir=workflows_dir, state_db_path=tmp_path / "state.sqlite3",
        log_level="INFO", instances=make_instances(), max_run_seconds=5.0,
    )

    run(settings)
    with sqlite3.connect(settings.state_db_path) as conn:
        first_count = conn.execute("SELECT COUNT(*) FROM execution_log").fetchone()[0]
    assert first_count == 1  # card_created fired

    # A brand new card on the next poll must be detected immediately -
    # nothing gates polling without webhooks configured.
    state["stack_id"] = 10
    run(settings)


def test_webhooks_enabled_skips_polling_until_pinged_or_fallback_due(tmp_path, monkeypatch):
    state = {"stack_id": 10}
    monkeypatch.setattr("requests.Session.request", fake_requests_for(state))

    workflows_dir = tmp_path / "workflows"
    workflows = YamlWorkflowRepository(workflows_dir)
    workflows.save(Workflow(
        id="wf-1", name="WF1", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_MOVED, stack_id=20),
        actions=(ActionStep(module="log_action", params={"message": "moved"}),),
    ))
    settings = Settings(
        workflows_dir=workflows_dir, state_db_path=tmp_path / "state.sqlite3",
        log_level="INFO", instances=make_instances(), max_run_seconds=5.0,
        webhooks=WebhookConfig(enabled=True, secret="x", fallback_poll_minutes=15.0),
    )

    run(settings)  # first run always polls (never polled before) - establishes the baseline snapshot

    state_store = SqliteStateStore(settings.state_db_path)
    _, last_polled_after_first_run = state_store.get_board_activity("prod", 1)
    assert last_polled_after_first_run is not None

    # Move the card "externally" (simulating a real change on Nextcloud) and
    # run again right away, with no webhook ping and well within the
    # fallback window - must NOT poll, so the move stays undetected for now.
    state["stack_id"] = 20
    run(settings)

    with sqlite3.connect(settings.state_db_path) as conn:
        count_before_ping = conn.execute("SELECT COUNT(*) FROM execution_log WHERE workflow_id = 'wf-1'").fetchone()[0]
    assert count_before_ping == 0

    # A webhook ping for this board arrives - the *next* run must poll
    # immediately and detect the already-happened move.
    state_store.record_webhook_ping("prod", 1, datetime.now(timezone.utc).isoformat())
    run(settings)

    with sqlite3.connect(settings.state_db_path) as conn:
        count_after_ping = conn.execute("SELECT COUNT(*) FROM execution_log WHERE workflow_id = 'wf-1'").fetchone()[0]
    assert count_after_ping == 1


def test_webhooks_enabled_still_polls_once_the_fallback_interval_elapses(tmp_path, monkeypatch):
    state = {"stack_id": 10}
    monkeypatch.setattr("requests.Session.request", fake_requests_for(state))

    workflows_dir = tmp_path / "workflows"
    workflows = YamlWorkflowRepository(workflows_dir)
    workflows.save(Workflow(
        id="wf-1", name="WF1", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_MOVED, stack_id=20),
        actions=(ActionStep(module="log_action", params={"message": "moved"}),),
    ))
    settings = Settings(
        workflows_dir=workflows_dir, state_db_path=tmp_path / "state.sqlite3",
        log_level="INFO", instances=make_instances(), max_run_seconds=5.0,
        webhooks=WebhookConfig(enabled=True, secret="x", fallback_poll_minutes=15.0),
    )
    run(settings)  # establishes the baseline

    state_store = SqliteStateStore(settings.state_db_path)
    # Back-date the last poll past the fallback window, as if a long time
    # had passed with no webhook ping ever arriving.
    stale = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
    with sqlite3.connect(settings.state_db_path) as conn:
        conn.execute("UPDATE board_activity SET last_polled_at = ? WHERE instance = 'prod' AND board_id = 1", (stale,))
        conn.commit()

    state["stack_id"] = 20
    run(settings)

    with sqlite3.connect(settings.state_db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM execution_log WHERE workflow_id = 'wf-1'").fetchone()[0]
    assert count == 1  # fallback kicked in - polled and detected the move even with no ping


def test_run_creates_a_link_and_executes_it_after_the_website_claims_it(tmp_path, monkeypatch):
    calls = []

    def fake_request(self, method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        if method == "GET" and url.endswith("/stacks"):
            return FakeResponse([{"id": 10, "cards": [{"id": 1, "title": "Card", "lastModified": 1}]}])
        return FakeResponse({})

    monkeypatch.setattr("requests.Session.request", fake_request)

    workflows_dir = tmp_path / "workflows"
    YamlWorkflowRepository(workflows_dir).save(Workflow(
        id="link-wf", name="Link", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_CREATED),
        actions=(ActionStep(module="create_action_link", id="lnk", params={
            "action": "add_comment", "action_params": {"message": "Per Link erledigt"},
            "success_message": "Erledigt!",
        }),),
    ))
    settings = Settings(
        workflows_dir=workflows_dir, state_db_path=tmp_path / "state.sqlite3", log_level="INFO",
        instances=make_instances(), max_run_seconds=5.0, public_url="https://site.example/deck",
    )
    state_store = SqliteStateStore(settings.state_db_path)

    run(settings)  # baseline poll: the existing card is "new" -> creates the link
    with sqlite3.connect(settings.state_db_path) as conn:
        rows = conn.execute("SELECT status, success_message FROM action_links").fetchall()
    assert rows == [("open", "Erledigt!")]
    assert not any("deckCard" in url for _, url, _ in calls)  # creating the link must not run the action

    with sqlite3.connect(settings.state_db_path) as conn:  # website/link.php claims it
        conn.execute("UPDATE action_links SET status = 'claimed', claimed_at = '2026-01-01T00:00:00+00:00'")
    run(settings)

    assert ("POST", "https://cloud.example.com/ocs/v2.php/apps/comments/api/v1/deckCard/1",
            {"message": "Per Link erledigt"}) in calls
    with sqlite3.connect(settings.state_db_path) as conn:
        status, error, payload = conn.execute("SELECT status, error, params_json FROM action_links").fetchone()
        logged = conn.execute(
            "SELECT workflow_id, module, success FROM execution_log WHERE module = 'add_comment'"
        ).fetchall()
    assert (status, error, payload) == ("done", None, None)
    assert logged == [("link-wf", "add_comment", 1)]

    run(settings)  # a done link never runs again
    assert sum(1 for _, url, _ in calls if "deckCard" in url) == 1
