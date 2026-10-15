from __future__ import annotations

from pathlib import Path

from automation.adapters.persistence.yaml_workflow_repository import YamlWorkflowRepository
from automation.core.domain.models import (
    ActionStep,
    ComparisonOp,
    Condition,
    EventType,
    IfStep,
    ScheduleTrigger,
    Trigger,
    Workflow,
)


def test_save_and_reload_roundtrip(tmp_path):
    repo = YamlWorkflowRepository(tmp_path)
    workflow = Workflow(
        id="wf-1",
        name="Test workflow",
        instance="prod",
        board_id=1,
        trigger=Trigger(event_type=EventType.CARD_MOVED, stack_id=5),
        actions=(ActionStep(module="log_action", params={"message": "hi"}),),
    )

    repo.save(workflow)

    assert repo.get("wf-1") == workflow
    assert (tmp_path / "wf-1.yaml").exists()


def test_list_enabled_filters_disabled(tmp_path):
    repo = YamlWorkflowRepository(tmp_path)
    enabled = Workflow(
        id="wf-a", name="A", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_CREATED), actions=(), enabled=True,
    )
    disabled = Workflow(
        id="wf-b", name="B", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_CREATED), actions=(), enabled=False,
    )
    repo.save(enabled)
    repo.save(disabled)

    assert {wf.id for wf in repo.list_enabled()} == {"wf-a"}
    assert {wf.id for wf in repo.list_all()} == {"wf-a", "wf-b"}


def test_get_missing_workflow_returns_none(tmp_path):
    repo = YamlWorkflowRepository(tmp_path)

    assert repo.get("does-not-exist") is None


def test_delete_removes_the_file(tmp_path):
    repo = YamlWorkflowRepository(tmp_path)
    workflow = Workflow(
        id="wf-1", name="A", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_CREATED), actions=(),
    )
    repo.save(workflow)

    repo.delete("wf-1")

    assert repo.get("wf-1") is None


def test_list_enabled_does_not_reread_unchanged_files(tmp_path, monkeypatch):
    repo = YamlWorkflowRepository(tmp_path)
    repo.save(Workflow(
        id="wf-1", name="A", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_CREATED), actions=(),
    ))
    repo.list_enabled()  # first call: populates the cache

    read_calls = []
    original_read_text = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        read_calls.append(self)
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    repo.list_enabled()
    repo.list_enabled()

    assert read_calls == []  # no file content was re-read - the cache was used


def test_list_enabled_reflects_a_file_changed_after_the_first_call(tmp_path):
    repo = YamlWorkflowRepository(tmp_path)
    workflow = Workflow(
        id="wf-1", name="A", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_CREATED), actions=(), enabled=True,
    )
    repo.save(workflow)
    assert {wf.id for wf in repo.list_enabled()} == {"wf-1"}

    # A second repository instance stands in for the website (a separate
    # process) disabling the workflow between cron runs - but here we
    # disable it through the *same* repo instance to specifically exercise
    # cache invalidation on save(), not just a fresh process's cold cache.
    repo.save(Workflow(
        id="wf-1", name="A", instance="prod", board_id=1,
        trigger=Trigger(event_type=EventType.CARD_CREATED), actions=(), enabled=False,
    ))

    assert {wf.id for wf in repo.list_enabled()} == set()


def test_roundtrip_with_a_schedule_trigger(tmp_path):
    repo = YamlWorkflowRepository(tmp_path)
    workflow = Workflow(
        id="daily-digest", name="Daily digest", instance="prod", board_id=1,
        trigger=Trigger(schedule=ScheduleTrigger(time="09:00", weekdays=(1, 2, 3, 4, 5))),
        actions=(ActionStep(module="log_action", params={"message": "good morning"}),),
    )

    repo.save(workflow)
    loaded = repo.get("daily-digest")

    assert loaded == workflow
    assert loaded.trigger.event_type is None
    assert loaded.trigger.schedule == ScheduleTrigger(time="09:00", weekdays=(1, 2, 3, 4, 5))


def test_roundtrip_with_a_schedule_trigger_and_no_weekdays(tmp_path):
    repo = YamlWorkflowRepository(tmp_path)
    workflow = Workflow(
        id="daily", name="Daily", instance="prod", board_id=1,
        trigger=Trigger(schedule=ScheduleTrigger(time="18:00")),
        actions=(ActionStep(module="log_action", params={"message": "evening"}),),
    )

    repo.save(workflow)
    loaded = repo.get("daily")

    assert loaded == workflow
    assert loaded.trigger.schedule.weekdays is None


def test_roundtrip_with_a_nested_if_else(tmp_path):
    repo = YamlWorkflowRepository(tmp_path)
    workflow = Workflow(
        id="wf-cond",
        name="Conditional",
        instance="prod",
        board_id=1,
        trigger=Trigger(event_type=EventType.CARD_CREATED),
        actions=(
            IfStep(
                condition=Condition(left={"$ref": "card.priority"}, op=ComparisonOp.EQ, right="high"),
                then_steps=(
                    ActionStep(module="add_label", id="urgent", params={"label_id": 1}),
                    IfStep(
                        condition=Condition(left=1, op=ComparisonOp.LT, right=2),
                        then_steps=(ActionStep(module="log_action", params={"message": "nested"}),),
                        else_steps=(),
                    ),
                ),
                else_steps=(ActionStep(module="log_action", params={"message": "not urgent"}),),
            ),
        ),
    )

    repo.save(workflow)
    loaded = repo.get("wf-cond")

    assert loaded == workflow
