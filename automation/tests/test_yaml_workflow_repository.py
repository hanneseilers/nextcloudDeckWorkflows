from __future__ import annotations

from automation.adapters.persistence.yaml_workflow_repository import YamlWorkflowRepository
from automation.core.domain.models import ActionStep, EventType, Trigger, Workflow


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
