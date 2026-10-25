from __future__ import annotations

import yaml

from automation.adapters.persistence.yaml_workflow_repository import YamlWorkflowRepository
from automation.core.domain.engine import WorkflowEngine
from automation.core.domain.models import (
    ActionStep, ComparisonOp, Condition, EventType, IfStep, Trigger, Workflow,
)
from automation.tests.test_engine import RecordingAction, make_event, make_workflow
from automation.testing.fakes import (
    InMemoryActionRegistry, InMemoryDeckGateway, InMemoryExecutionLog, InMemoryWorkflowRepository,
)


def run(actions, registry):
    log = InMemoryExecutionLog()
    engine = WorkflowEngine(
        workflows=InMemoryWorkflowRepository([make_workflow(actions=actions)]),
        actions=InMemoryActionRegistry(registry), execution_log=log,
    )
    return engine.handle(make_event(), deck=InMemoryDeckGateway()), log


def test_a_disabled_step_is_skipped_and_the_others_run():
    first, second, third = RecordingAction(), RecordingAction(), RecordingAction()
    results, _ = run(
        (ActionStep(module="a"), ActionStep(module="b", enabled=False), ActionStep(module="c")),
        {"a": first, "b": second, "c": third},
    )
    assert (len(first.calls), len(second.calls), len(third.calls)) == (1, 0, 1)
    assert [r.module for r in results[0].action_results] == ["a", "c"]  # nothing in the history for the skipped one
    assert results[0].success


def test_enabled_is_the_default():
    assert ActionStep(module="x").enabled is True
    assert IfStep(condition=Condition(left=1, op=ComparisonOp.EQ, right=1)).enabled is True


def test_a_disabled_if_block_is_skipped_whole_condition_and_both_branches():
    inside, after = RecordingAction(), RecordingAction()
    block = IfStep(
        condition=Condition(left={"$ref": "no.such"}, op=ComparisonOp.EQ, right=1),  # would log a warning if it were evaluated
        then_steps=(ActionStep(module="inside"),), else_steps=(ActionStep(module="inside"),), enabled=False,
    )
    results, _ = run((block, ActionStep(module="after")), {"inside": inside, "after": after})
    assert len(inside.calls) == 0 and len(after.calls) == 1


def test_a_disabled_step_inside_an_enabled_if_branch_is_skipped():
    kept, skipped = RecordingAction(), RecordingAction()
    block = IfStep(
        condition=Condition(left=1, op=ComparisonOp.EQ, right=1),
        then_steps=(ActionStep(module="skipped", enabled=False), ActionStep(module="kept")),
    )
    run((block,), {"kept": kept, "skipped": skipped})
    assert (len(kept.calls), len(skipped.calls)) == (1, 0)


def test_a_reference_to_a_disabled_step_resolves_to_nothing_and_does_not_crash():
    producer, consumer = RecordingAction(), RecordingAction()
    results, _ = run(
        (ActionStep(module="p", id="prod", enabled=False), ActionStep(module="c", params={"value": {"$ref": "prod.x"}})),
        {"p": producer, "c": consumer},
    )
    assert consumer.calls[0][1] == {"value": None} and len(producer.calls) == 0 and results[0].success


def test_disabling_is_saved_only_when_off_and_comes_back(tmp_path):
    repo = YamlWorkflowRepository(tmp_path)
    workflow = Workflow(
        id="wf", name="W", instance="prod", board_id=1, trigger=Trigger(event_type=EventType.CARD_CREATED),
        actions=(
            ActionStep(module="log_action", id="on", params={"message": "a"}),
            ActionStep(module="log_action", id="off", params={"message": "b"}, enabled=False),
            IfStep(condition=Condition(left=1, op=ComparisonOp.EQ, right=1),
                   then_steps=(ActionStep(module="log_action", enabled=False),), enabled=False),
        ),
    )
    repo.save(workflow)
    data = yaml.safe_load((tmp_path / "wf.yaml").read_text())
    assert "enabled" not in data["actions"][0]                       # untouched steps look like before
    assert data["actions"][1]["enabled"] is False and data["actions"][2]["enabled"] is False
    assert data["actions"][2]["then"][0]["enabled"] is False

    [loaded] = repo.list_all()
    assert [getattr(s, "enabled") for s in loaded.actions] == [True, False, False]
    assert loaded.actions[2].then_steps[0].enabled is False
    assert loaded == workflow


def test_only_an_explicit_false_switches_a_step_off(tmp_path):
    (tmp_path / "wf.yaml").write_text(
        "id: wf\nname: W\nnickname: x\nenabled: true\nnextcloud_instance: prod\nboard_id: 1\ntrigger: {event: card_created}\n"
        "actions:\n"
        "  - {module: log_action, id: a}\n"                       # no key (every old workflow)
        "  - {module: log_action, id: b, enabled: true}\n"
        "  - {module: log_action, id: c, enabled: 0}\n"           # odd values: stay on
        "  - {module: log_action, id: d, enabled: 'false'}\n"
        "  - {module: log_action, id: e, enabled: false}\n"
    )
    [workflow] = YamlWorkflowRepository(tmp_path).list_all()
    assert [s.enabled for s in workflow.actions] == [True, True, True, True, False]
