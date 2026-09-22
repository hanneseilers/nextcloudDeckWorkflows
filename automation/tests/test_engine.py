from __future__ import annotations

from automation import actions_registry
from automation.adapters.actions.loader import ModuleLoader
from automation.core.domain.engine import WorkflowEngine
from automation.core.domain.models import ActionStep, DeckEvent, EventType, Trigger, Workflow
from automation.testing.fakes import (
    InMemoryActionRegistry,
    InMemoryDeckGateway,
    InMemoryExecutionLog,
    InMemoryWorkflowRepository,
)


class RecordingAction:
    ACTION_NAME = "recording"

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def execute(self, context, params) -> None:
        self.calls.append((context.event, params))


class FailingAction:
    ACTION_NAME = "failing"

    def execute(self, context, params) -> None:
        raise RuntimeError("boom")


def make_workflow(**overrides) -> Workflow:
    defaults = dict(
        id="wf-1",
        name="Test workflow",
        instance="test",
        board_id=1,
        trigger=Trigger(event_type=EventType.CARD_CREATED, stack_id=10),
        actions=(ActionStep(module="recording", params={"foo": "bar"}),),
        enabled=True,
    )
    defaults.update(overrides)
    return Workflow(**defaults)


def make_event(**overrides) -> DeckEvent:
    defaults = dict(instance="test", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10)
    defaults.update(overrides)
    return DeckEvent(**defaults)


def test_matching_event_triggers_the_configured_action():
    action = RecordingAction()
    engine = WorkflowEngine(
        workflows=InMemoryWorkflowRepository([make_workflow()]),
        actions=InMemoryActionRegistry({"recording": action}),
        execution_log=InMemoryExecutionLog(),
    )
    event = make_event()

    results = engine.handle(event, deck=InMemoryDeckGateway())

    assert len(results) == 1
    assert results[0].success
    assert action.calls == [(event, {"foo": "bar"})]


def test_event_in_a_different_stack_does_not_trigger():
    action = RecordingAction()
    engine = WorkflowEngine(
        workflows=InMemoryWorkflowRepository([make_workflow()]),
        actions=InMemoryActionRegistry({"recording": action}),
        execution_log=InMemoryExecutionLog(),
    )

    results = engine.handle(make_event(stack_id=999), deck=InMemoryDeckGateway())

    assert results == []
    assert action.calls == []


def test_disabled_workflow_is_skipped():
    action = RecordingAction()
    engine = WorkflowEngine(
        workflows=InMemoryWorkflowRepository([make_workflow(enabled=False)]),
        actions=InMemoryActionRegistry({"recording": action}),
        execution_log=InMemoryExecutionLog(),
    )

    assert engine.handle(make_event(), deck=InMemoryDeckGateway()) == []


def test_failing_action_is_recorded_but_does_not_raise():
    execution_log = InMemoryExecutionLog()
    engine = WorkflowEngine(
        workflows=InMemoryWorkflowRepository(
            [make_workflow(actions=(ActionStep(module="failing", params={}),))]
        ),
        actions=InMemoryActionRegistry({"failing": FailingAction()}),
        execution_log=execution_log,
    )

    results = engine.handle(make_event(), deck=InMemoryDeckGateway())

    assert len(results) == 1
    assert not results[0].success
    assert results[0].action_results[0].error == "boom"
    assert len(execution_log.results) == 1


def test_one_event_runs_all_configured_actions_in_order():
    """A single workflow can chain several standard action modules; they all run,
    in order, for the one event that triggered the workflow."""

    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 1, "lastModified": 1}]}, {"id": 20, "cards": []}]})
    workflow = make_workflow(
        actions=(
            ActionStep(module="move_card", params={"target_stack_id": 20}),
            ActionStep(module="assign_user", params={"user_id": "alice"}),
            ActionStep(module="add_comment", params={"message": "moved and assigned"}),
        )
    )
    engine = WorkflowEngine(
        workflows=InMemoryWorkflowRepository([workflow]),
        actions=ModuleLoader(actions_registry),
        execution_log=InMemoryExecutionLog(),
    )

    results = engine.handle(make_event(), deck=deck)

    assert len(results) == 1
    assert results[0].success
    assert [r.module for r in results[0].action_results] == ["move_card", "assign_user", "add_comment"]
    assert deck.stacks[1][0]["cards"] == []
    moved_card = deck.stacks[1][1]["cards"][0]
    assert moved_card["assignees"] == ["alice"]
    assert ("add_comment", 1, "moved and assigned") in deck.calls
