from __future__ import annotations

import logging

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
        context = ActionContext(event=event, deck=deck)
        result = ExecutionResult(workflow_id=workflow.id, event=event)
        for step in workflow.actions:
            try:
                action = self._actions.get(step.module)
                action.execute(context, step.params)
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
