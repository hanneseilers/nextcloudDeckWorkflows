from __future__ import annotations

import logging
from typing import Any

from automation.core.domain.models import ActionResult, DeckEvent, ExecutionResult, Workflow
from automation.core.ports.action_module import ActionContext, ActionModulePort
from automation.core.ports.deck_gateway import DeckGatewayPort
from automation.core.ports.execution_log import ExecutionLogPort
from automation.core.ports.workflow_repository import WorkflowRepositoryPort

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """Application service: matches an incoming event against configured workflows and
    runs their action chain. Depends only on ports, so it can be unit-tested with
    in-memory fakes (see automation.testing.fakes) without any real infrastructure.
    """

    def __init__(
        self,
        workflows: WorkflowRepositoryPort,
        actions: ActionModulePort,
        execution_log: ExecutionLogPort,
    ) -> None:
        self._workflows = workflows
        self._actions = actions
        self._execution_log = execution_log

    def handle(self, event: DeckEvent, deck: DeckGatewayPort) -> list[ExecutionResult]:
        results = []
        for workflow in self._workflows.list_enabled():
            if not workflow.matches(event):
                continue
            result = self._run(workflow, event, deck)
            self._execution_log.record(result)
            results.append(result)
        return results

    def _run(self, workflow: Workflow, event: DeckEvent, deck: DeckGatewayPort) -> ExecutionResult:
        # Shared with ActionContext.variables (same dict object, not a copy) so
        # a SetVariableAction's writes show up immediately both via
        # {"$ref": "vars.<name>"} and in context.variables for $placeholder
        # substitution in free text (send_email, add_comment).
        variables: dict[str, Any] = {}
        context = ActionContext(event=event, deck=deck, modules=self._actions, variables=variables)
        result = ExecutionResult(workflow_id=workflow.id, event=event)
        # Seeded before any step runs: lets every step's params reference the
        # triggering card's raw Nextcloud fields directly via {"$ref": "card.<field>"}
        # (e.g. "card.title", "card.duedate") without needing a lookup module.
        outputs_by_step: dict[str, dict[str, Any]] = {"card": dict(event.card), "vars": variables}

        for index, step in enumerate(workflow.actions):
            step_key = step.id or str(index)
            try:
                action = self._actions.get(step.module)
                params = _resolve_params(step.params, outputs_by_step)
                output = action.execute(context, params) or {}
                outputs_by_step[step_key] = output
                result.action_results.append(ActionResult(module=step.module, success=True))
            except Exception as exc:
                # Action modules are dynamically loaded, third-party-ish plugin code: one
                # failing step must not abort the rest of the workflow run or the whole
                # cron invocation, so failures are isolated and recorded instead of raised.
                logger.exception("Action '%s' failed for workflow '%s'", step.module, workflow.id)
                result.action_results.append(
                    ActionResult(module=step.module, success=False, error=str(exc))
                )
        return result


def _resolve_params(params: Any, outputs_by_step: dict[str, dict[str, Any]]) -> Any:
    """Recursively resolves a step's params against prior steps' outputs.

    A dict of exactly {"$ref": "<step_id>.<field>"} is replaced by that field's
    value from the referenced step's output (see _resolve_ref); every other
    value - including a dict with other/additional keys - is a literal, passed
    through unchanged (recursing into nested dicts/lists so a $ref can appear
    anywhere, e.g. inside send_email's template_data).
    """

    if isinstance(params, dict):
        if set(params) == {"$ref"} and isinstance(params["$ref"], str):
            return _resolve_ref(params["$ref"], outputs_by_step)
        return {key: _resolve_params(value, outputs_by_step) for key, value in params.items()}
    if isinstance(params, list):
        return [_resolve_params(item, outputs_by_step) for item in params]
    return params


def _resolve_ref(ref: str, outputs_by_step: dict[str, dict[str, Any]]) -> Any:
    """Resolves "<step_id>.<field>[.<nested_field>...]" against recorded step
    outputs. A step that hasn't run yet (wrong order), doesn't exist, or didn't
    produce the requested field resolves to None with a logged warning rather
    than raising - a bad mapping shouldn't crash the workflow, just leave the
    downstream action to fail its own validation of that one field.
    """

    step_id, _, path = ref.partition(".")
    value: Any = outputs_by_step.get(step_id)
    if value is None:
        logger.warning("Could not resolve '$ref: %s': no recorded output for step '%s'", ref, step_id)
        return None
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            logger.warning("Could not resolve '$ref: %s': no field '%s' in step '%s' output", ref, part, step_id)
            return None
        value = value[part]
    return value
