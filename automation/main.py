"""Cron entry point: `python -m automation.main`.

Wires the hexagon together (composition root) and runs every enabled workflow once
against the events detected since the previous run. Intended to be invoked
periodically by a cron job on shared webspace hosting.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from automation import actions_registry
from automation.adapters.actions.loader import ModuleLoader
from automation.adapters.nextcloud.calendar_gateway import NextcloudCalendarGateway
from automation.adapters.nextcloud.client import NextcloudClient
from automation.adapters.nextcloud.deck_gateway import NextcloudDeckGateway
from automation.adapters.nextcloud.event_source import PollingEventSource
from automation.adapters.null_deck_gateway import NullDeckGateway
from automation.adapters.persistence.sqlite_state_store import SqliteStateStore
from automation.adapters.run_lock import RunLock
from automation.adapters.smtp_config import load_smtp_config, send_email as smtp_send
from automation.adapters.persistence.yaml_workflow_repository import YamlWorkflowRepository
from automation.config.settings import REPO_ROOT, Settings, load_settings
from automation.core.domain.engine import WorkflowEngine
from automation.core.domain.models import ActionResult, DeckEvent, EventType, ExecutionResult
from automation.core.domain.schedule import should_fire
from automation.core.domain.webhook_gate import should_poll_now

logger = logging.getLogger(__name__)

# Where the website (website/src/ModuleRegistry.php) reads the available action
# modules from. Independent of any Nextcloud/settings config - listing modules
# only needs the local actions_registry package - so it's refreshed on every
# invocation of this script, dry-run or not, even if config/*.yaml is missing.
MODULES_SNAPSHOT_PATH = REPO_ROOT / "automation" / "var" / "modules.json"


@dataclass(frozen=True)
class BoardTarget:
    """One board this run polls/handles events for - built once per board in
    run() below, then polled repeatedly by the fixed-point loop. A named
    tuple (not a plain positional one) because this has grown a field each
    time a new per-run dependency (event_source, then calendar) was added."""

    instance_name: str
    board_id: int
    deck: NextcloudDeckGateway
    event_source: PollingEventSource
    calendar: NextcloudCalendarGateway


def run(settings: Settings) -> None:
    # Started before anything else: max_run_seconds has to stay below the
    # host's cron kill limit, so the links/test runs/schedules handled before
    # polling count against it too.
    deadline = time.monotonic() + settings.max_run_seconds
    workflows = YamlWorkflowRepository(settings.workflows_dir)
    state_store = SqliteStateStore(settings.state_db_path)
    action_loader = ModuleLoader(actions_registry)
    engine = WorkflowEngine(
        workflows=workflows,
        actions=action_loader,
        execution_log=state_store,
        sequence_store=state_store,
        link_store=state_store,
        public_url=settings.public_url,
        dedupe_store=state_store,
        copy_store=state_store,
        display_timezone=settings.timezone,
    )

    try:
        _process_action_links(settings, state_store, engine)
    except Exception:
        # Degrade, don't crash: a broken link row must not stop every board's polling.
        logger.exception("Could not process one-time links - continuing with the rest of the run")
    _process_test_runs(settings, workflows, state_store, engine)
    _process_schedules(workflows, state_store, engine)

    boards_by_instance: dict[str, set[int]] = {}
    for workflow in workflows.list_enabled():
        boards_by_instance.setdefault(workflow.instance, set()).add(workflow.board_id)

    # Built once, polled repeatedly below - a board's deck/event_source don't
    # change between iterations of the fixed-point loop.
    targets: list[BoardTarget] = []
    for instance_name, board_ids in boards_by_instance.items():
        instance = settings.instances.get(instance_name)
        if instance is None:
            logger.error(
                "Skipping instance '%s': not configured in config/nextcloud.yaml", instance_name
            )
            continue

        client = NextcloudClient(instance.base_url, instance.username, instance.app_password)
        deck = NextcloudDeckGateway(client)
        event_source = PollingEventSource(deck, state_store)
        # Same Nextcloud account/client as `deck` above - CalDAV needs no
        # separate credentials or config/nextcloud.yaml entry.
        calendar = NextcloudCalendarGateway(client, instance.username)
        for board_id in board_ids:
            targets.append(BoardTarget(instance_name, board_id, deck, event_source, calendar))

    targets = _apply_webhook_gate(settings, state_store, targets)

    def mark_unfinished(target: BoardTarget) -> None:
        # The webhook gate already marked this board as polled; without a
        # fresh "ping" the next runs would skip it until fallback_poll_minutes
        # passes, leaving the events the time budget didn't reach waiting.
        if settings.webhooks is not None and settings.webhooks.enabled:
            state_store.record_webhook_ping(
                target.instance_name, target.board_id, datetime.now(timezone.utc).isoformat()
            )

    # A workflow's own actions (move a card, change its due date, ...) can be
    # exactly what triggers another workflow - so keep re-polling and
    # re-running for as long as the previous pass found at least one event,
    # bounded by max_run_seconds. A run that hits the bound simply stops; the
    # per-board commit-after-handling below (see PollingEventSource) means
    # nothing already-committed gets reprocessed, and anything still pending
    # gets picked up again on the very next cron invocation - no separate
    # "which iteration were we on" state needs to survive a crash.
    iteration = 0
    while True:
        iteration += 1
        if iteration > 1:
            # A link visited while this (possibly long) run is going can't get
            # its own immediate run - the run lock is held - so pick it up
            # here instead of leaving it for the next cron invocation.
            try:
                _run_claimed_links(settings, state_store, engine)
            except Exception:
                logger.exception("Could not process one-time links - continuing with the rest of the run")
        any_triggered = False
        for target in targets:
            if _process_board(engine, target, deadline, on_unfinished=mark_unfinished):
                any_triggered = True

        if not any_triggered:
            logger.info("Fixed point reached after %d iteration(s) - run complete", iteration)
            break

        if time.monotonic() >= deadline:
            logger.warning(
                "max_run_seconds (%s) exceeded after %d iteration(s) - stopping; "
                "anything still pending will be picked up on the next run",
                settings.max_run_seconds, iteration,
            )
            break

    _process_failure_notifications(settings, workflows, state_store)
    try:
        state_store.purge_history(
            (datetime.now(timezone.utc) - timedelta(days=settings.history_retention_days)).isoformat()
        )
    except Exception:
        logger.exception("Could not purge old history")
    # Only reached if everything above completed without an unhandled
    # exception - the website's health check reads this to tell "cron is
    # actually still running" from "it crashed/stopped being invoked". UTC,
    # unlike _process_schedules' deliberately-local `now` below - this one is
    # only ever compared against itself (by PHP, a separate runtime/process),
    # so it must be unambiguous rather than "whatever this server's local
    # timezone happens to be".
    state_store.set_heartbeat(datetime.now(timezone.utc).isoformat())


def _apply_webhook_gate(
    settings: Settings, state_store: SqliteStateStore, targets: list[BoardTarget]
) -> list[BoardTarget]:
    """Without settings.webhooks configured, every board is polled on
    every invocation (unchanged default behavior). Once configured, a
    board is only skipped this run if it's been polled before, has no
    fresh webhook ping, and isn't yet due for its fallback poll - see
    core/domain/webhook_gate.should_poll_now. A board that's included
    records a fresh last_polled_at right away (not just on success) so
    the gate reflects "we decided to check this board now", independent
    of whether the actual poll succeeds.
    """

    if settings.webhooks is None or not settings.webhooks.enabled:
        return targets

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    kept = []
    for target in targets:
        last_ping_raw, last_polled_raw = state_store.get_board_activity(target.instance_name, target.board_id)
        last_ping = datetime.fromisoformat(last_ping_raw) if last_ping_raw else None
        last_polled = datetime.fromisoformat(last_polled_raw) if last_polled_raw else None

        if should_poll_now(settings.webhooks.fallback_poll_minutes, now, last_ping, last_polled):
            state_store.record_poll(target.instance_name, target.board_id, now_iso)
            kept.append(target)
        else:
            logger.debug(
                "Skipping board %s on instance '%s' this run - no fresh webhook ping, "
                "not yet due for fallback poll", target.board_id, target.instance_name,
            )
    return kept


def _process_board(
    engine: WorkflowEngine,
    target: BoardTarget,
    deadline: float,
    on_unfinished: Optional[Callable[[BoardTarget], None]] = None,
) -> bool:
    """One instance being unreachable or one board having disappeared must not stop
    the rest of the run - polling errors here are logged and this board is skipped.

    Progress is saved card by card: once every event of a card has been
    handled, that card's new state is stored right away (see
    PollingEventSource.advance), and the board's full snapshot is committed
    after the last one. If the process dies partway through (SIGKILL
    included), the next run re-detects only the cards not yet advanced -
    their events are rerun rather than silently lost ("at least once"), but
    the cards already done are not repeated.

    Stops starting new events once `deadline` (time.monotonic) has passed -
    the unhandled ones are simply detected again by the next run - and then
    returns True so the caller's loop ends on its own time check. Returns
    whether at least one event was handled, so the caller's fixed-point loop
    knows whether to poll again.
    """

    if time.monotonic() >= deadline:
        if on_unfinished is not None:
            on_unfinished(target)
        return True  # out of time before even polling - the caller's deadline check ends the run

    try:
        events = list(target.event_source.poll(target.instance_name, target.board_id))
    except Exception:
        logger.exception(
            "Skipping board %s on instance '%s': could not poll for events",
            target.board_id, target.instance_name,
        )
        return False

    # Events of one card are consecutive (see PollingEventSource._diff), so a
    # card is done once its last event has been handled.
    last_event_of_card = {event.card_id: index for index, event in enumerate(events)}
    for index, event in enumerate(events):
        if time.monotonic() >= deadline:
            logger.warning(
                "Time budget used up on board %s (instance '%s') - %d event(s) left for the next run",
                target.board_id, target.instance_name, len(events) - index,
            )
            if on_unfinished is not None:
                on_unfinished(target)
            return True
        logger.info(
            "Detected %s on card %s (instance=%s board=%s)",
            event.event_type.value, event.card_id, target.instance_name, target.board_id,
        )
        engine.handle(event, target.deck, target.calendar)
        if last_event_of_card[event.card_id] == index:
            target.event_source.advance(target.instance_name, target.board_id, event.card_id)

    target.event_source.commit(target.instance_name, target.board_id)
    return len(events) > 0


def _process_test_runs(
    settings: Settings,
    workflows: YamlWorkflowRepository,
    state_store: SqliteStateStore,
    engine: WorkflowEngine,
) -> None:
    """Processes "Testlauf" requests the website queued (see
    SqliteStateStore.enqueue_test_run) - runs a specific, user-chosen
    workflow against a specific, user-chosen real card right now, regardless
    of whether that workflow's trigger would otherwise match, or whether the
    workflow is even enabled. Every failure mode (unknown workflow, instance,
    or card) is recorded back onto the request as a clear error instead of
    raising, so the website always has something to show.
    """

    for pending in state_store.pending_test_runs():
        test_run_id, workflow_id, card_id = pending["id"], pending["workflow_id"], pending["card_id"]
        try:
            workflow = workflows.get(workflow_id)
            if workflow is None:
                raise RuntimeError(f"Workflow '{workflow_id}' nicht gefunden")

            instance = settings.instances.get(workflow.instance)
            if instance is None:
                raise RuntimeError(f"Nextcloud-Instanz '{workflow.instance}' nicht konfiguriert")

            client = NextcloudClient(instance.base_url, instance.username, instance.app_password)
            deck = NextcloudDeckGateway(client)
            calendar = NextcloudCalendarGateway(client, instance.username)

            card, stack_id = _find_card(deck, workflow.board_id, card_id)
            if card is None:
                raise RuntimeError(f"Karte {card_id} nicht auf Board {workflow.board_id} gefunden")

            event = DeckEvent(
                instance=workflow.instance,
                board_id=workflow.board_id,
                event_type=workflow.trigger.event_type,
                card_id=card_id,
                stack_id=stack_id,
                card=card,
            )
            _, run_id = engine.run_single(workflow, event, deck, calendar)
            state_store.complete_test_run(test_run_id, run_id=run_id)
        except Exception as exc:
            logger.exception("Test-run %s (workflow '%s') failed", test_run_id, workflow_id)
            state_store.complete_test_run(test_run_id, error=str(exc))


# A link still "running" after this long was left behind by a killed process.
STALE_LINK_RUN_MINUTES = 15


def _link_event(link: dict[str, Any]) -> DeckEvent:
    return DeckEvent(
        instance=link["instance"],
        board_id=link["board_id"],
        event_type=link["event_type"],
        card_id=link["card_id"],
        stack_id=link["stack_id"],
        card=link["card"],
    )


def _process_action_links(settings: Settings, state_store: SqliteStateStore, engine: WorkflowEngine) -> None:
    """Runs the one-time links visitors have claimed through website/link.php
    (see create_action_link) - each one's action, against the card/context
    captured when the link was created. Every failure is recorded on the
    link itself, so the page the visitor is looking at always gets an answer.
    Finished links older than a day are purged.
    """

    # A link left in "running" by a killed process (cron timeout) is NOT
    # re-run - that could execute its action twice (a duplicate email or
    # comment); it is marked failed and shows up as a failed run in the
    # history instead, so someone can decide whether to create a new link.
    stale_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STALE_LINK_RUN_MINUTES)).isoformat()
    for link in state_store.stale_running_links(stale_cutoff):
        message = "Verarbeitung abgebrochen: der Prozess wurde vor Abschluss beendet (z. B. Cron-Timeout)"
        logger.warning("One-time link for workflow '%s' was left running - marking it failed", link["workflow_id"])
        try:
            state_store.record(ExecutionResult(
                workflow_id=link["workflow_id"],
                event=_link_event(link),
                action_results=[ActionResult(module=link["module"], success=False, error=message)],
            ))
        except Exception:
            logger.exception("Could not record the aborted link run")
        state_store.finish_link(link["token_hash"], error=message)

    _run_claimed_links(settings, state_store, engine)

    state_store.purge_finished_links((datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
    state_store.purge_expired_links(datetime.now(timezone.utc).replace(microsecond=0).isoformat())


def _run_claimed_links(settings: Settings, state_store: SqliteStateStore, engine: WorkflowEngine) -> None:
    """Runs every claimed, not yet started link - see _process_action_links.

    The card's column is looked up again right before the action runs: a link
    is often opened hours after it was created, and the card may have been
    moved since. The Deck card-update route carries the stack id, so running
    against the column captured at creation could fail, or (unverified) put
    the card back into that old column. Falls back to the captured column if
    the card can't be found on the board (deleted, or a card-less schedule).
    """

    for link in state_store.claimed_links():
        token_hash = link["token_hash"]
        if not state_store.begin_link_run(token_hash):
            continue  # another main.py invocation took it
        try:
            instance = settings.instances.get(link["instance"])
            if instance is None:
                raise RuntimeError(f"Nextcloud-Instanz '{link['instance']}' nicht konfiguriert")
            client = NextcloudClient(instance.base_url, instance.username, instance.app_password)
            deck = NextcloudDeckGateway(client)
            current_stack_id = link["current_stack_id"]
            if link["card_id"]:
                _, live_stack_id = _find_card(deck, link["board_id"], link["card_id"])
                if live_stack_id is not None:
                    current_stack_id = live_stack_id
            result, _ = engine.run_link_action(
                workflow_id=link["workflow_id"],
                event=_link_event(link),
                current_stack_id=current_stack_id,
                module=link["module"],
                params=link["params"],
                variables=link["variables"],
                deck=deck,
                calendar=NextcloudCalendarGateway(client, instance.username),
            )
            failure = next((r.error for r in result.action_results if not r.success), None)
            state_store.finish_link(token_hash, error=failure)
        except Exception as exc:
            logger.exception("One-time link for workflow '%s' failed", link["workflow_id"])
            state_store.finish_link(token_hash, error=str(exc))


def _find_card(deck: NextcloudDeckGateway, board_id: int, card_id: int) -> tuple[Optional[dict], Optional[int]]:
    for stack in deck.list_stacks(board_id):
        for card in stack.get("cards", []):
            if card.get("id") == card_id:
                return card, stack["id"]
    return None, None


def _process_schedules(
    workflows: YamlWorkflowRepository, state_store: SqliteStateStore, engine: WorkflowEngine
) -> None:
    """Runs every enabled, schedule-triggered workflow whose time has come
    (see core/domain/schedule.should_fire) - independent of the Deck-event
    polling above. Uses a synthetic, card-less event and a NullDeckGateway,
    so a schedule-triggered workflow should stick to card-independent
    actions; one that doesn't gets a clear error instead of silently doing
    nothing, recorded like any other failed action.
    """

    now = datetime.now()
    deck = NullDeckGateway()
    for workflow in workflows.list_enabled():
        schedule = workflow.trigger.schedule
        if schedule is None:
            continue

        try:
            last_fired_raw = state_store.get_last_fired(workflow.id)
            last_fired = datetime.fromisoformat(last_fired_raw) if last_fired_raw else None
            if not should_fire(schedule, now, last_fired):
                continue

            event = DeckEvent(
                instance=workflow.instance,
                board_id=workflow.board_id,
                event_type=EventType.CARD_UPDATED,  # never checked - run_single bypasses matches()
                card_id=0,
                stack_id=0,
            )
            logger.info("Schedule fired for workflow '%s'", workflow.id)
            engine.run_single(workflow, event, deck)
            state_store.set_last_fired(workflow.id, now.isoformat())
        except Exception:
            logger.exception("Schedule check failed for workflow '%s'", workflow.id)


def _process_failure_notifications(
    settings: Settings, workflows: YamlWorkflowRepository, state_store: SqliteStateStore
) -> None:
    """Emails settings.error_notifications.to once a workflow has failed
    `threshold` times in a row - and, after it recovers, once more if it
    later fails that many times again. A "streak" is tracked per workflow
    (failure_notifications table) so this notifies exactly once per streak,
    not on every single tick while the workflow stays broken.
    """

    config = settings.error_notifications
    if config is None or not config.enabled:
        return

    for workflow in workflows.list_enabled():
        try:
            outcomes = state_store.recent_run_outcomes(workflow.id, limit=config.threshold)
            consecutive_failures = 0
            for success in outcomes:
                if success:
                    break
                consecutive_failures += 1

            if consecutive_failures < config.threshold:
                state_store.clear_notified_failure_streak(workflow.id)
                continue

            if state_store.has_notified_failure_streak(workflow.id):
                continue

            smtp_send(
                load_smtp_config(),
                to=config.to,
                subject=f"Workflow '{workflow.name}' schlägt wiederholt fehl",
                body=(
                    f"Der Workflow '{workflow.name}' (Id: {workflow.id}) ist seit mindestens "
                    f"{consecutive_failures} Lauf/Läufen in Folge fehlgeschlagen.\n\n"
                    "Details siehe Ausführungs-Historie in der Website."
                ),
            )
            state_store.mark_notified_failure_streak(workflow.id)
        except Exception:
            logger.exception("Failure-notification check failed for workflow '%s'", workflow.id)


def _modules_snapshot() -> dict[str, Any]:
    """Describes every currently loadable action module as JSON - name, hard
    dependencies, and its default_input()/default_output() example objects.
    This is what the website reads to render the module picker and its
    per-module parameter form; see automation/README.md."""

    loader = ModuleLoader(actions_registry)
    modules = []
    for name in loader.list_names():
        action = loader.get(name)
        modules.append({
            "name": name,
            "label": getattr(action, "LABEL", "") or name,
            "description": getattr(action, "DESCRIPTION", ""),
            "param_labels": dict(getattr(action, "PARAM_LABELS", {})),
            "param_help": dict(getattr(action, "PARAM_HELP", {})),
            "output_labels": dict(getattr(action, "OUTPUT_LABELS", {})),
            "requires": list(getattr(action, "REQUIRES", ())),
            "input": action.default_input(),
            "output": action.default_output(),
        })
    return {"modules": modules}


def _write_modules_snapshot(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_modules_snapshot(), indent=2))
    except Exception:
        # The website falls back to "no modules found" if this is stale/missing -
        # never let a snapshot-writing problem stop the actual workflow run.
        logger.exception("Could not write module snapshot to %s", path)


def run_dry_run() -> None:
    """Exercises the full wiring with in-memory fakes - no config files, no network,
    no real Nextcloud instance needed. Smoke test for `python -m automation.main --dry-run`.
    """

    from automation.core.domain.models import ActionStep, EventType, Trigger, Workflow
    from automation.testing.fakes import (
        InMemoryDeckGateway,
        InMemoryExecutionLog,
        InMemorySnapshotStore,
        InMemoryWorkflowRepository,
    )

    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": []}]})
    workflow = Workflow(
        id="dry-run-demo",
        name="Dry-run demo",
        instance="dry-run",
        board_id=1,
        trigger=Trigger(event_type=EventType.CARD_CREATED, stack_id=10),
        actions=(ActionStep(module="log_action", params={"message": "dry-run card created"}),),
    )
    workflows = InMemoryWorkflowRepository([workflow])
    snapshots = InMemorySnapshotStore()
    execution_log = InMemoryExecutionLog()
    action_loader = ModuleLoader(actions_registry)
    engine = WorkflowEngine(workflows=workflows, actions=action_loader, execution_log=execution_log)
    event_source = PollingEventSource(deck, snapshots)

    event_source.poll("dry-run", 1)  # establish the baseline snapshot (empty stack)
    event_source.commit("dry-run", 1)
    logger.info("Dry-run: adding a card to stack 10 to trigger 'card_created'")
    deck.stacks[1][0]["cards"].append({"id": 100, "lastModified": 1})

    events = event_source.poll("dry-run", 1)
    for event in events:
        results = engine.handle(event, deck)
        for result in results:
            logger.info("Executed workflow '%s' -> success=%s", result.workflow_id, result.success)
    event_source.commit("dry-run", 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run configured Nextcloud Deck workflows once.")
    parser.add_argument("--config-dir", default=None, help="Override the config/ directory location")
    parser.add_argument("--log-level", default=None, help="Override the configured log level, e.g. DEBUG")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run the wiring against in-memory fakes instead of real config/Nextcloud",
    )
    parser.add_argument(
        "--wait-lock", type=float, default=0.0, metavar="SECONDS",
        help="If another run is in progress, wait up to this long for it to finish "
             "instead of exiting right away (used for the immediate runs the website starts)",
    )
    parser.add_argument(
        "--list-modules", action="store_true",
        help="Print the available action modules (name, requires, input/output shape) as JSON and exit",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level or "INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    if args.list_modules:
        print(json.dumps(_modules_snapshot(), indent=2))
        return

    # Independent of everything below: keep the website's module list fresh on
    # every invocation, whether or not Nextcloud config is even valid.
    _write_modules_snapshot(MODULES_SNAPSHOT_PATH)

    if args.dry_run:
        run_dry_run()
        return

    try:
        settings = load_settings(args.config_dir)
    except Exception:
        # No usable config is not a crash - there's nothing to do this run, log why
        # and stop cleanly so the cron job keeps invoking us on schedule regardless.
        logger.exception("Could not load configuration - nothing to do this run")
        return

    logging.getLogger().setLevel(args.log_level or settings.log_level)

    # One run at a time: an overlapping invocation (cron firing again before
    # the previous run finished, or a webhook/link-triggered one) would handle
    # the same events twice. The OS drops the lock if this process is killed.
    lock = RunLock(settings.state_db_path.parent / "run.lock")
    if not lock.acquire():
        if args.wait_lock <= 0:
            logger.info("Another run is in progress - exiting; the next invocation picks up what is left")
            return
        # Only one invocation needs to queue behind the running one: the run it
        # makes afterwards covers every link/ping that came in meanwhile. Any
        # further immediate run (a burst of webhook pings) exits right away
        # instead of each holding a process for up to --wait-lock seconds.
        queue = RunLock(settings.state_db_path.parent / "run.queue.lock")
        if not queue.acquire():
            logger.info("Another run is in progress and one is already waiting for it - exiting")
            return
        try:
            acquired = lock.acquire(args.wait_lock)
        finally:
            queue.release()
        if not acquired:
            logger.info("Another run is still in progress - exiting; the next invocation picks up what is left")
            return
    try:
        run(settings)
    except Exception:
        logger.exception("Unhandled error - stopping this run without crashing the process")
    finally:
        lock.release()


if __name__ == "__main__":
    main()
