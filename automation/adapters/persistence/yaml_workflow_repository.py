from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from automation.core.domain.models import ActionStep, EventType, Trigger, Workflow

logger = logging.getLogger(__name__)


class YamlWorkflowRepository:
    """Implements WorkflowRepositoryPort. Stores one human-readable YAML file per
    workflow under a directory (by default the top-level workflows/ storage)."""

    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)

    def list_enabled(self) -> list[Workflow]:
        return [wf for wf in self._load_all() if wf.enabled]

    def list_all(self) -> list[Workflow]:
        return self._load_all()

    def get(self, workflow_id: str) -> Optional[Workflow]:
        path = self._path_for(workflow_id)
        if not path.exists():
            return None
        return self._parse(yaml.safe_load(path.read_text()))

    def save(self, workflow: Workflow) -> None:
        self._path_for(workflow.id).write_text(yaml.safe_dump(self._to_dict(workflow), sort_keys=False))

    def delete(self, workflow_id: str) -> None:
        self._path_for(workflow_id).unlink(missing_ok=True)

    def _path_for(self, workflow_id: str) -> Path:
        return self._directory / f"{workflow_id}.yaml"

    def _load_all(self) -> list[Workflow]:
        workflows = []
        for path in sorted(self._directory.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text())
                if data:
                    workflows.append(self._parse(data))
            except Exception:
                # A single malformed workflow file must not take every other
                # workflow down with it - skip it, log it, keep going.
                logger.exception("Skipping invalid workflow file %s", path)
        return workflows

    @staticmethod
    def _parse(data: dict) -> Workflow:
        trigger_data = data["trigger"]
        trigger = Trigger(
            event_type=EventType(trigger_data["event"]),
            stack_id=trigger_data.get("stack_id"),
        )
        actions = tuple(
            ActionStep(module=step["module"], id=step.get("id", ""), params=step.get("params") or {})
            for step in data.get("actions", [])
        )
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
        trigger: dict = {"event": workflow.trigger.event_type.value}
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


def _step_to_dict(step: ActionStep) -> dict:
    data: dict = {"module": step.module}
    if step.id:
        data["id"] = step.id
    data["params"] = dict(step.params)
    return data
