"""Cron entry point: `python -m automation.main`.

Wires the hexagon together (composition root) and runs every enabled workflow once
against the events detected since the previous run. Intended to be invoked
periodically by a cron job on shared webspace hosting.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from automation import actions_registry
from automation.adapters.actions.loader import ModuleLoader
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

        for board_id in board_ids:
            _process_board(engine, event_source, deck, instance_name, board_id)


def _process_board(
    engine: WorkflowEngine,
    event_source: PollingEventSource,
    deck: NextcloudDeckGateway,
    instance_name: str,
    board_id: int,
) -> None:
    """One instance being unreachable or one board having disappeared must not stop
    the rest of the run - polling errors here are logged and this board is skipped."""

    try:
        events = event_source.poll(instance_name, board_id)
    except Exception:
        logger.exception(
            "Skipping board %s on instance '%s': could not poll for events", board_id, instance_name
        )
        return

    for event in events:
        logger.info(
            "Detected %s on card %s (instance=%s board=%s)",
            event.event_type.value, event.card_id, instance_name, board_id,
        )
        engine.handle(event, deck)


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
    logger.info("Dry-run: adding a card to stack 10 to trigger 'card_created'")
    deck.stacks[1][0]["cards"].append({"id": 100, "lastModified": 1})

    for event in event_source.poll("dry-run", 1):
        results = engine.handle(event, deck)
        for result in results:
            logger.info("Executed workflow '%s' -> success=%s", result.workflow_id, result.success)


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
