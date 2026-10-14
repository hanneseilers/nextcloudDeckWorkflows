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
from pathlib import Path
from typing import Any

from automation import actions_registry
from automation.adapters.actions.loader import ModuleLoader
from automation.adapters.nextcloud.calendar_gateway import NextcloudCalendarGateway
from automation.adapters.nextcloud.client import NextcloudClient
from automation.adapters.nextcloud.deck_gateway import NextcloudDeckGateway
from automation.adapters.nextcloud.event_source import PollingEventSource
from automation.adapters.persistence.sqlite_state_store import SqliteStateStore
from automation.adapters.persistence.yaml_workflow_repository import YamlWorkflowRepository
from automation.config.settings import REPO_ROOT, Settings, load_settings
from automation.core.domain.engine import WorkflowEngine

logger = logging.getLogger(__name__)

# Where the website (website/src/ModuleRegistry.php) reads the available action
# modules from. Independent of any Nextcloud/settings config - listing modules
# only needs the local actions_registry package - so it's refreshed on every
# invocation of this script, dry-run or not, even if config/*.yaml is missing.
MODULES_SNAPSHOT_PATH = REPO_ROOT / "automation" / "var" / "modules.json"


def run(settings: Settings) -> None:
    workflows = YamlWorkflowRepository(settings.workflows_dir)
    state_store = SqliteStateStore(settings.state_db_path)
    action_loader = ModuleLoader(actions_registry)
    engine = WorkflowEngine(workflows=workflows, actions=action_loader, execution_log=state_store)

    boards_by_instance: dict[str, set[int]] = {}
    for workflow in workflows.list_enabled():
        boards_by_instance.setdefault(workflow.instance, set()).add(workflow.board_id)

    # Built once, polled repeatedly below - a board's deck/event_source don't
    # change between iterations of the fixed-point loop.
    targets: list[tuple[str, int, NextcloudDeckGateway, PollingEventSource, NextcloudCalendarGateway]] = []
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
            targets.append((instance_name, board_id, deck, event_source, calendar))

    # A workflow's own actions (move a card, change its due date, ...) can be
    # exactly what triggers another workflow - so keep re-polling and
    # re-running for as long as the previous pass found at least one event,
    # bounded by max_run_seconds. A run that hits the bound simply stops; the
    # per-board commit-after-handling below (see PollingEventSource) means
    # nothing already-committed gets reprocessed, and anything still pending
    # gets picked up again on the very next cron invocation - no separate
    # "which iteration were we on" state needs to survive a crash.
    deadline = time.monotonic() + settings.max_run_seconds
    iteration = 0
    while True:
        iteration += 1
        any_triggered = False
        for instance_name, board_id, deck, event_source, calendar in targets:
            if _process_board(engine, event_source, deck, calendar, instance_name, board_id):
                any_triggered = True

        if not any_triggered:
            logger.info("Fixed point reached after %d iteration(s) - run complete", iteration)
            return

        if time.monotonic() >= deadline:
            logger.warning(
                "max_run_seconds (%s) exceeded after %d iteration(s) - stopping; "
                "anything still pending will be picked up on the next run",
                settings.max_run_seconds, iteration,
            )
            return


def _process_board(
    engine: WorkflowEngine,
    event_source: PollingEventSource,
    deck: NextcloudDeckGateway,
    calendar: NextcloudCalendarGateway,
    instance_name: str,
    board_id: int,
) -> bool:
    """One instance being unreachable or one board having disappeared must not stop
    the rest of the run - polling errors here are logged and this board is skipped.

    Only commits the new snapshot after every detected event has been fully
    handled (not inside poll() itself) - if the process dies partway through
    handling, the next run re-detects and reruns the same events rather than
    silently losing them. Returns whether at least one event was handled, so
    the caller's fixed-point loop knows whether to poll again.
    """

    try:
        events = event_source.poll(instance_name, board_id)
    except Exception:
        logger.exception(
            "Skipping board %s on instance '%s': could not poll for events", board_id, instance_name
        )
        return False

    for event in events:
        logger.info(
            "Detected %s on card %s (instance=%s board=%s)",
            event.event_type.value, event.card_id, instance_name, board_id,
        )
        engine.handle(event, deck, calendar)

    event_source.commit(instance_name, board_id)
    return len(events) > 0


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

    try:
        run(settings)
    except Exception:
        logger.exception("Unhandled error - stopping this run without crashing the process")


if __name__ == "__main__":
    main()
