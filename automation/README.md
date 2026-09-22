# automation

Cron-driven workflow engine, built as a hexagonal (ports & adapters) architecture.

## Layout

- `core/domain/` — framework-free domain model (`Workflow`, `DeckEvent`, ...) and the `WorkflowEngine` application service. No I/O.
- `core/ports/` — abstract interfaces the core depends on (`WorkflowRepositoryPort`, `DeckGatewayPort`, `EventSourcePort`, `ActionModulePort`, `ExecutionLogPort`).
- `adapters/nextcloud/` — talks to the Nextcloud/Deck REST API; detects events by polling and diffing board state against the last snapshot (no webhooks needed).
- `adapters/persistence/` — `YamlWorkflowRepository` (workflow definitions as YAML in `workflows/`) and `SqliteStateStore` (snapshot + execution log, `automation/var/state.sqlite3`).
- `adapters/actions/` — dynamically loads action modules from `actions_registry/`.
- `actions_registry/` — one file per action capability. Drop in a new file that subclasses `WorkflowAction` to add a capability; no other code needs to change. Ships with standard card-editing actions: `set_title`, `set_description`, `set_due_date`, `move_card`, `add_label`, `assign_user`, `unassign_user`, `add_comment` (plus `log_action` as a no-op reference/smoke-test action).
- `main.py` — cron entry point / composition root.

A workflow's `actions` is a list, run in order by the `WorkflowEngine` - a single event (e.g. "card created in stack X") can trigger several actions, such as moving the card and assigning a user and posting a comment. One failing action is logged and does not stop the rest of the chain from running.

## Running

```bash
pip install -r automation/requirements-dev.txt
cp config/nextcloud.example.yaml config/nextcloud.yaml   # then fill in your instance(s)
cp config/settings.example.yaml config/settings.yaml

python -m automation.main            # one real run, driven by workflows/*.yaml
python -m automation.main --dry-run  # wiring smoke test, no config/network needed
pytest                                # unit tests against in-memory fakes
```

Schedule `python -m automation.main` via cron for periodic execution.

## Adding a new action module

Create `automation/actions_registry/<name>.py`:

```python
from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext

class MyAction(WorkflowAction):
    ACTION_NAME = "my_action"

    def execute(self, context: ActionContext, params: dict) -> None:
        ...  # use context.event and context.deck (a DeckGatewayPort)
```

Reference it from a workflow YAML's `actions[].module` field.
