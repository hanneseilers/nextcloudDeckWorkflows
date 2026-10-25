from __future__ import annotations

import itertools
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterator, Optional

from automation.core.domain.date_values import date_values
from automation.core.domain.models import (
    ActionResult,
    ActionStep,
    ComparisonOp,
    DeckEvent,
    EventType,
    ExecutionResult,
    IfStep,
    Workflow,
    WorkflowStep,
)
from automation.core.ports.action_link_store import ActionLinkStorePort
from automation.core.ports.action_module import ActionContext, ActionModulePort
from automation.core.ports.calendar_gateway import CalendarGatewayPort
from automation.core.ports.copy_store import CopyStorePort
from automation.core.ports.deck_gateway import DeckGatewayPort
from automation.core.ports.duplicate_guard import DuplicateGuardPort
from automation.core.ports.execution_log import ExecutionLogPort
from automation.core.ports.sequence_store import SequenceStorePort
from automation.core.ports.workflow_repository import WorkflowRepositoryPort

logger = logging.getLogger(__name__)


@dataclass
class _RunState:
    """Bundles everything shared across one workflow run's recursive step
    walk but that doesn't change per step/branch - threading it as one
    object keeps _run_steps/_run_action_step's signatures from growing a
    parameter every time another cross-cutting concern (if/else, the
    fallback-id counter) is added."""

    outputs_by_step: dict[str, dict[str, Any]]
    result: ExecutionResult
    workflow_id: str
    fallback_ids: Iterator[int]


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
        sequence_store: Optional[SequenceStorePort] = None,
        link_store: Optional[ActionLinkStorePort] = None,
        public_url: Optional[str] = None,
        dedupe_store: Optional[DuplicateGuardPort] = None,
        copy_store: Optional[CopyStorePort] = None,
        display_timezone: str = "Europe/Berlin",
    ) -> None:
        self._workflows = workflows
        self._actions = actions
        self._execution_log = execution_log
        # Unlike `calendar` (passed per handle() call - it varies per Nextcloud
        # instance), the sequence store is the same one store for this
        # engine's whole lifetime, so it's a constructor dependency instead.
        self._sequence_store = sequence_store
        self._link_store = link_store
        self._public_url = public_url
        self._dedupe_store = dedupe_store
        self._copy_store = copy_store
        self._display_timezone = display_timezone
        # (workflow id, card id, column id) combinations handle() already ran
        # during this engine's lifetime - main.run() builds a fresh engine per
        # invocation, so this is "once per run". See handle().
        self._handled: set[tuple[str, int, int]] = set()

    def handle(
        self,
        event: DeckEvent,
        deck: DeckGatewayPort,
        calendar: Optional[CalendarGatewayPort] = None,
    ) -> list[ExecutionResult]:
        results = []
        for workflow in self._workflows.list_enabled():
            if not workflow.matches(event):
                continue
            # A workflow that changes a card makes the very next poll see that
            # change as a new event - which would run the same workflow again,
            # and again. So each (workflow, card, column) combination runs at
            # most once per invocation; a different workflow, or the same one
            # for the card in a different column, still runs. Known trade-offs
            # (kept on purpose): a workflow whose own action moves the card to
            # another column can run once more there, and a workflow that
            # already ran for this card/column earlier in the same invocation
            # is not triggered again by another workflow's later change.
            key = (workflow.id, event.card_id, event.stack_id)
            if key in self._handled:
                logger.info(
                    "Skipping workflow '%s' for card %s in column %s: already ran for it during this run",
                    workflow.id, event.card_id, event.stack_id,
                )
                continue
            if self._is_own_copy(workflow, event):
                logger.info(
                    "Skipping workflow '%s' for card %s: the card is its own copy (copy_card)",
                    workflow.id, event.card_id,
                )
                continue
            self._handled.add(key)
            # Only event-triggered runs use send_email's duplicate guard: a
            # test run, schedule or link is a deliberate new run every time.
            result = self._run(workflow, event, deck, calendar, dedupe=True)
            try:
                self._execution_log.record(result)
            except Exception:
                # Persisting this run's log entry must not abort every other
                # workflow/board still pending this cron tick (and, via the
                # caller, main.py's heartbeat update) - same "degrade, don't
                # crash" stance already applied to each action step below.
                logger.exception("Could not record execution log for workflow '%s'", workflow.id)
            results.append(result)
        return results

    def run_single(
        self,
        workflow: Workflow,
        event: DeckEvent,
        deck: DeckGatewayPort,
        calendar: Optional[CalendarGatewayPort] = None,
    ) -> tuple[ExecutionResult, str]:
        """Runs exactly this workflow against this event, regardless of
        whether workflow.matches(event) or even workflow.enabled - used by
        main.py's test-run processing to let someone try a specific workflow
        against a real, chosen card on demand. Still goes through the normal
        action chain and is still recorded to the execution log exactly like
        a real trigger (so it shows up in the website's history view too),
        returning the run id for the caller to link back to it.
        """

        result = self._run(workflow, event, deck, calendar)
        run_id = self._execution_log.record(result)
        return result, run_id

    def run_link_actions(
        self,
        workflow_id: str,
        event: DeckEvent,
        current_stack_id: int,
        steps: list[dict[str, Any]],
        variables: dict[str, Any],
        deck: DeckGatewayPort,
        calendar: Optional[CalendarGatewayPort] = None,
    ) -> tuple[ExecutionResult, str]:
        """Runs a one-time link's actions - up to five, in order - in the
        context (card, stack, variables) the link captured when it was created,
        see create_action_link and main.py::_process_action_links. One run in
        the execution log like any other, attributed to the workflow that
        created the link. Each step is {"module": ..., "params": ...}; the
        params were already $ref-resolved at link-creation time (so one action
        can't read another's output, but a variable they share is the same).

        One failing action doesn't stop the next one (same as the steps of a
        workflow); the card's column carries on from action to action, so a
        move_card first makes the later ones act on the new column."""

        context = ActionContext(
            event=event,
            deck=deck,
            modules=self._actions,
            variables=variables,
            calendar=calendar,
            sequence_store=self._sequence_store,
            workflow_id=workflow_id,
            copy_store=self._copy_store,
            display_timezone=self._display_timezone,
            link_store=self._link_store,  # for revoke_action_links
        )
        context.current_stack_id = current_stack_id
        result = ExecutionResult(workflow_id=workflow_id, event=event)
        for step in steps:
            module = step["module"]
            try:
                self._actions.get(module).execute(context, step.get("params") or {})
                result.action_results.append(ActionResult(module=module, success=True))
            except Exception as exc:
                logger.exception("Link action '%s' failed for workflow '%s'", module, workflow_id)
                result.action_results.append(ActionResult(module=module, success=False, error=str(exc)))
        run_id = self._execution_log.record(result)
        return result, run_id

    def _is_own_copy(self, workflow: Workflow, event: DeckEvent) -> bool:
        if self._copy_store is None or event.event_type != EventType.CARD_CREATED:
            return False
        try:
            info = self._copy_store.copy_info(event.instance, event.board_id, event.card_id)
        except Exception:
            logger.exception("Could not look up copy information for card %s", event.card_id)
            return False
        return info is not None and info[0] == workflow.id

    def _run(
        self,
        workflow: Workflow,
        event: DeckEvent,
        deck: DeckGatewayPort,
        calendar: Optional[CalendarGatewayPort],
        dedupe: bool = False,
    ) -> ExecutionResult:
        # Shared with ActionContext.variables (same dict object, not a copy) so
        # a SetVariableAction's writes show up immediately both via
        # {"$ref": "vars.<name>"} and in context.variables for $placeholder
        # substitution in free text (send_email, add_comment).
        variables: dict[str, Any] = {}
        context = ActionContext(
            event=event,
            deck=deck,
            modules=self._actions,
            variables=variables,
            calendar=calendar,
            sequence_store=self._sequence_store,
            workflow_id=workflow.id,
            link_store=self._link_store,
            public_url=self._public_url,
            dedupe_store=self._dedupe_store if dedupe else None,
            copy_store=self._copy_store,
            display_timezone=self._display_timezone,
        )
        result = ExecutionResult(workflow_id=workflow.id, event=event)
        # Seeded before any step runs: lets every step's params reference the
        # triggering card's raw Nextcloud fields directly via {"$ref": "card.<field>"}
        # (e.g. "card.title", "card.duedate") without needing a lookup module.
        # "now": the date values ($date/$day/$weekday as references), from the start of the run.
        outputs_by_step: dict[str, dict[str, Any]] = {
            "card": dict(event.card), "vars": variables, "now": date_values(self._display_timezone),
        }
        # One counter shared across the whole (possibly nested) run, so two
        # id-less steps in different if/else branches never collide on the
        # same fallback key - see _run_steps.
        state = _RunState(
            outputs_by_step=outputs_by_step,
            result=result,
            workflow_id=workflow.id,
            fallback_ids=itertools.count(),
        )

        self._run_steps(workflow.actions, context, state)
        return result

    def _run_steps(self, steps: tuple[WorkflowStep, ...], context: ActionContext, state: _RunState) -> None:
        for step in steps:
            if not step.enabled:
                # Switched off in the editor: skipped like it wasn't there - no output (a
                # later {"$ref": ...} to it resolves to nothing), no history entry, and an
                # if-block's condition isn't even evaluated.
                logger.debug("Skipping disabled step in workflow '%s'", state.workflow_id)
                continue
            if isinstance(step, IfStep):
                left = _resolve_params(step.condition.left, state.outputs_by_step)
                right = _resolve_params(step.condition.right, state.outputs_by_step)
                try:
                    branch_is_then = _evaluate_condition(step.condition.op, left, right)
                except Exception:
                    # A bad/unevaluable condition takes the else branch rather
                    # than aborting the workflow - same "degrade, don't crash"
                    # stance as everything else here.
                    logger.exception("Could not evaluate if-condition in workflow '%s'", state.workflow_id)
                    branch_is_then = False
                branch = step.then_steps if branch_is_then else step.else_steps
                self._run_steps(branch, context, state)
                continue

            self._run_action_step(step, context, state)

    def _run_action_step(self, step: ActionStep, context: ActionContext, state: _RunState) -> None:
        step_key = step.id or str(next(state.fallback_ids))
        try:
            action = self._actions.get(step.module)
            params = _resolve_params(step.params, state.outputs_by_step)
            output = action.execute(context, params) or {}
            state.outputs_by_step[step_key] = output
            state.result.action_results.append(ActionResult(module=step.module, success=True))
        except Exception as exc:
            # Action modules are dynamically loaded, third-party-ish plugin code: one
            # failing step must not abort the rest of the workflow run or the whole
            # cron invocation, so failures are isolated and recorded instead of raised.
            logger.exception("Action '%s' failed for workflow '%s'", step.module, state.workflow_id)
            state.result.action_results.append(
                ActionResult(module=step.module, success=False, error=str(exc))
            )


_REF_AS_TEXT = re.compile(r'^\s*\{\s*"?\$ref"?\s*:\s*"?([^"}\s]+)"?\s*\}\s*$')


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
    if isinstance(params, str) and _REF_AS_TEXT.match(params):
        # The shorthand from the docs, but as a quoted string: it's plain text.
        logger.warning(
            "A value is the text %r, not a reference - write it as an object: {\"$ref\": \"%s\"}",
            params.strip(), _REF_AS_TEXT.match(params).group(1),
        )
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


def _try_numeric(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None  # don't silently treat True/False as 1/0 in a comparison
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _evaluate_condition(op: ComparisonOp, left: Any, right: Any) -> bool:
    """Evaluates an IfStep's condition. eq/ne/lt/gt compare numerically if
    both sides parse as numbers (so a YAML int and a Nextcloud-API string
    like "5" compare equal), otherwise as strings for lt/gt and with a plain
    `==`/`!=` for eq/ne. contains/beginswith/endswith always compare as
    strings - that's the point of them.
    """

    left_num, right_num = _try_numeric(left), _try_numeric(right)
    both_numeric = left_num is not None and right_num is not None

    if op == ComparisonOp.EQ:
        return left_num == right_num if both_numeric else left == right
    if op == ComparisonOp.NE:
        return not _evaluate_condition(ComparisonOp.EQ, left, right)
    if op == ComparisonOp.LT:
        return left_num < right_num if both_numeric else str(left) < str(right)
    if op == ComparisonOp.GT:
        return left_num > right_num if both_numeric else str(left) > str(right)
    if op == ComparisonOp.CONTAINS:
        return str(right) in str(left)
    if op == ComparisonOp.BEGINS_WITH:
        return str(left).startswith(str(right))
    if op == ComparisonOp.ENDS_WITH:
        return str(left).endswith(str(right))
    raise ValueError(f"Unknown comparison operator: {op!r}")
