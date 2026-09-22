# automation

Cron-driven workflow engine, built as a hexagonal (ports & adapters) architecture.

## Layout

- `core/domain/` — framework-free domain model (`Workflow`, `DeckEvent`, ...) and the `WorkflowEngine` application service. No I/O.
- `core/ports/` — abstract interfaces the core depends on (`WorkflowRepositoryPort`, `DeckGatewayPort`, `EventSourcePort`, `ActionModulePort`, `ExecutionLogPort`).
- `adapters/nextcloud/` — talks to the Nextcloud/Deck REST API; detects events by polling and diffing board state against the last snapshot (no webhooks needed).
- `adapters/persistence/` — `YamlWorkflowRepository` (workflow definitions as YAML in `workflows/`) and `SqliteStateStore` (snapshot + execution log, `automation/var/state.sqlite3`).
- `adapters/actions/` — dynamically loads action modules from `actions_registry/`.
- `actions_registry/` — one file per action capability. Drop in a new file that subclasses `WorkflowAction` to add a capability; no other code needs to change. Ships with standard card-editing actions: `set_title`, `set_description`, `set_due_date`, `move_card`, `add_label`, `assign_user`, `unassign_user`, `add_comment`; plus `send_email` (SMTP, own config, see below) and `calendar_lookup` (data-lookup reference module, not wired to anything yet); plus `log_action` as a no-op reference/smoke-test action.
- `main.py` — cron entry point / composition root.

A workflow's `actions` is a list, run in order by the `WorkflowEngine` - a single event (e.g. "card created in stack X") can trigger several actions, such as moving the card and assigning a user and posting a comment. One failing action is logged and does not stop the rest of the chain from running.

## Modules calling modules

An action can call another action module directly through `context.modules` (the
same `ActionModulePort` registry the engine itself uses):

```python
def execute(self, context: ActionContext, params: dict) -> None:
    appointment = context.modules.get("calendar_lookup").execute(context, {...})
    ...  # use appointment's return value, e.g. to fill an email body
```

- `context.modules.list_names()` - which other modules are currently available.
- `context.modules.get(name)` - fetch one and run it; raises `UnknownActionError`
  (a `KeyError`) if it isn't available - catch it for an optional dependency.
- `WorkflowAction.REQUIRES = ("other_action", ...)` - declare a *hard* dependency.
  The loader checks this at startup and disables (with a log message) any action
  whose required module(s) aren't all loadable, instead of letting it fail
  unpredictably the first time it runs. Dependency chains cascade: if `b` requires
  `a` and `a` gets disabled, `b` is disabled too.

## Fault tolerance

The system is meant to keep doing *something* useful even in a degraded
environment (Nextcloud unreachable, a board deleted, an action module broken or
removed) - never crash the whole cron run. Each layer logs and skips its own unit
instead of propagating:

- a broken/missing action file → that one action is disabled (`ModuleLoader`)
- a malformed workflow YAML file → that one workflow is skipped (`YamlWorkflowRepository`)
- an unreachable Nextcloud instance or a vanished board → that instance/board is
  skipped for this run (`main.py::run`)
- a failing action step → recorded as a failed step, the rest of the workflow's
  actions still run (`WorkflowEngine`, already true for nested module calls too)
- missing/invalid config → logged, the run ends cleanly instead of raising (`main.py::main`)

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

## send_email

Sends mail via SMTP. Server settings are its own file, `config/smtp.yaml` (copy
`config/smtp.example.yaml`; gitignored like the other real config files) -
separate from `settings.yaml` since it's specific to this one action. Body/subject
either come directly as `params.subject`/`params.body`, or from a template file
in `config/email_templates/<name>.txt` (first line `Subject: ...`, blank line,
then the body) referenced via `params.template`. `$placeholder` values from
`params.template_data` are substituted (`string.Template.safe_substitute` -
an unresolved placeholder is left as-is rather than raising). See
`config/email_templates/example.txt`.

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
