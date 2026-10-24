from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from automation.core.domain.models import (
    ActionStep,
    ComparisonOp,
    Condition,
    EventType,
    IfStep,
    ScheduleTrigger,
    Trigger,
    Workflow,
    WorkflowStep,
)

logger = logging.getLogger(__name__)


class YamlWorkflowRepository:
    """Implements WorkflowRepositoryPort. Stores one human-readable YAML file per
    workflow under a directory (by default the top-level workflows/ storage).

    The directory may contain subfolders (the website's folders, nested as
    deep as it likes - they only organize the files): every *.yaml below it
    counts, except inside hidden (.dot) folders. A workflow's file is always
    named <id>.yaml and ids are unique across all folders; should the same id
    appear twice anyway, the first file in path order wins and the other is
    logged and ignored (running both would double every action)."""

    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._cache: Optional[list[Workflow]] = None
        self._cache_signature: Optional[tuple] = None

    def list_enabled(self) -> list[Workflow]:
        return [wf for wf in self._load_all() if wf.enabled]

    def list_all(self) -> list[Workflow]:
        return self._load_all()

    def get(self, workflow_id: str) -> Optional[Workflow]:
        path = self._existing_path(workflow_id)
        if path is None:
            return None
        return self._parse(yaml.safe_load(path.read_text()))

    def save(self, workflow: Workflow) -> None:
        # A workflow that already exists is rewritten where it lives (in its
        # folder); a new one goes to the top level.
        path = self._existing_path(workflow.id) or self._directory / f"{workflow.id}.yaml"
        path.write_text(yaml.safe_dump(self._to_dict(workflow), sort_keys=False))
        self._cache = None  # force a fresh _load_all() even if mtimes happened to collide

    def delete(self, workflow_id: str) -> None:
        path = self._existing_path(workflow_id)
        if path is not None:
            path.unlink(missing_ok=True)
        self._cache = None

    def _yaml_files(self) -> list[Path]:
        """Every workflow file below the directory, in path order, skipping
        anything inside a hidden (.dot) folder."""

        return sorted(
            path for path in self._directory.rglob("*.yaml")
            if not any(part.startswith(".") for part in path.relative_to(self._directory).parts[:-1])
        )

    def _existing_path(self, workflow_id: str) -> Optional[Path]:
        for path in self._yaml_files():
            if path.name == f"{workflow_id}.yaml":
                return path
        return None

    def _load_all(self) -> list[Workflow]:
        # WorkflowEngine.handle() calls list_enabled() once per event, and a
        # single run can process many events across several fixed-point
        # iterations (see main.py) - re-reading and re-parsing every
        # workflow file's content on every one of those calls is pure waste
        # when nothing in workflows/ has changed since the last call.
        # Re-stat'ing every file (cheap: no content read, no YAML parsing)
        # to build a (name, mtime) signature is enough to detect any change
        # - a file added/removed/edited - without caching anything stale.
        signature = self._directory_signature()
        if self._cache is not None and signature == self._cache_signature:
            return self._cache

        workflows = []
        seen_ids: dict[str, Path] = {}
        for path in self._yaml_files():
            try:
                data = yaml.safe_load(path.read_text())
                if data:
                    workflow = self._parse(data)
                    if workflow.id in seen_ids:
                        logger.error(
                            "Ignoring %s: workflow id '%s' is already used by %s (ids must be unique across folders)",
                            path, workflow.id, seen_ids[workflow.id],
                        )
                        continue
                    seen_ids[workflow.id] = path
                    workflows.append(workflow)
            except Exception:
                # A single malformed workflow file must not take every other
                # workflow down with it - skip it, log it, keep going.
                logger.exception("Skipping invalid workflow file %s", path)

        self._cache = workflows
        self._cache_signature = signature
        return workflows

    def _directory_signature(self) -> tuple:
        return tuple(
            (str(path.relative_to(self._directory)), path.stat().st_mtime_ns) for path in self._yaml_files()
        )

    @staticmethod
    def _parse(data: dict) -> Workflow:
        trigger_data = data["trigger"]
        if "schedule" in trigger_data:
            schedule_data = trigger_data["schedule"]
            weekdays = schedule_data.get("weekdays")
            trigger = Trigger(schedule=ScheduleTrigger(
                time=schedule_data["time"],
                weekdays=tuple(weekdays) if weekdays else None,
            ))
        else:
            trigger = Trigger(
                event_type=EventType(trigger_data["event"]),
                stack_id=trigger_data.get("stack_id"),
            )
        actions = _parse_steps(data.get("actions", []))
        return Workflow(
            id=data["id"],
            name=data.get("name", data["id"]),
            instance=data["nextcloud_instance"],
            board_id=data["board_id"],
            trigger=trigger,
            actions=actions,
            enabled=data.get("enabled", True),
        )

    @staticmethod
    def _to_dict(workflow: Workflow) -> dict:
        if workflow.trigger.schedule is not None:
            schedule: dict = {"time": workflow.trigger.schedule.time}
            if workflow.trigger.schedule.weekdays:
                schedule["weekdays"] = list(workflow.trigger.schedule.weekdays)
            trigger: dict = {"schedule": schedule}
        else:
            trigger = {"event": workflow.trigger.event_type.value}
            if workflow.trigger.stack_id is not None:
                trigger["stack_id"] = workflow.trigger.stack_id
        return {
            "id": workflow.id,
            "name": workflow.name,
            "enabled": workflow.enabled,
            "nextcloud_instance": workflow.instance,
            "board_id": workflow.board_id,
            "trigger": trigger,
            "actions": [_step_to_dict(step) for step in workflow.actions],
        }


def _parse_steps(items: list) -> tuple[WorkflowStep, ...]:
    return tuple(_parse_step(item) for item in items)


def _parse_step(data: dict) -> WorkflowStep:
    if data.get("type") == "if":
        condition_data = data["condition"]
        condition = Condition(
            left=condition_data["left"],
            op=ComparisonOp(condition_data["op"]),
            right=condition_data["right"],
        )
        return IfStep(
            condition=condition,
            then_steps=_parse_steps(data.get("then", [])),
            else_steps=_parse_steps(data.get("else", [])),
        )
    return ActionStep(module=data["module"], id=data.get("id", ""), params=data.get("params") or {})


def _steps_to_list(steps: tuple[WorkflowStep, ...]) -> list:
    return [_step_to_dict(step) for step in steps]


def _step_to_dict(step: WorkflowStep) -> dict:
    if isinstance(step, IfStep):
        return {
            "type": "if",
            "condition": {
                "left": step.condition.left,
                "op": step.condition.op.value,
                "right": step.condition.right,
            },
            "then": _steps_to_list(step.then_steps),
            "else": _steps_to_list(step.else_steps),
        }
    data: dict = {"module": step.module}
    if step.id:
        data["id"] = step.id
    data["params"] = dict(step.params)
    return data
