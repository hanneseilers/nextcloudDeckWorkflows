# Creating and activating your own action modules

A **module** (or "action") is one capability a workflow step can perform -
`set_title`, `send_email`, `generate_random_number`, and so on. This guide
walks through writing a new one from scratch, using a deliberately simple
example: a module that converts a piece of text to upper case.

It covers the mechanics of adding a module. For the full picture of what a
workflow can do with one once it exists (`$ref` mappings, `if`/`else`,
global variables, the triggering card's own fields, ...), see
[automation/README.md](automation/README.md).

## 1. Write the module

Every module is one Python file under `automation/actions_registry/`,
containing one class that subclasses `WorkflowAction`. Create
`automation/actions_registry/uppercase_text.py`:

```python
from __future__ import annotations

from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class UppercaseTextAction(WorkflowAction):
    """Converts a piece of text to upper case.

    params:
      text: str - the text to convert

    output:
      text: str - the upper-cased text
    """

    ACTION_NAME: ClassVar[str] = "uppercase_text"

    def default_input(self) -> dict[str, Any]:
        return {"text": ""}

    def default_output(self) -> dict[str, Any]:
        return {"text": ""}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        return {"text": params["text"].upper()}
```

What each piece is for:

- **`ACTION_NAME`** — the id a workflow's `module:` field references. Must
  be unique across all modules.
- **`default_input()`/`default_output()`** — an *example* object documenting
  the shapes `params`/the return value are expected to have. This is what
  the website reads to render the module's parameter form and to offer its
  output fields for `$ref` mapping - always declare these, even though the
  base class technically defaults to `{}` ("no particular shape").
- **`execute(context, params)`** — does the actual work and returns a plain
  JSON-shaped object (`dict`/`list`/`str`/`int`/`float`/`bool`/`None` only -
  the same thing a workflow YAML can hold). `params` is already resolved:
  any `{"$ref": ...}` mapping from an earlier step has already been
  replaced with the real value by the time `execute()` sees it.
- **`context`** (an `ActionContext`) gives access to everything else a
  module might need: `context.event` (the triggering `DeckEvent`),
  `context.deck` (a `DeckGatewayPort` for reading/writing the Nextcloud
  board), `context.variables` (the workflow run's global variables),
  `context.calendar`/`context.sequence_store` (optional, `None` outside a
  real run - see automation/README.md for what uses them). This example
  needs none of them; a card-editing action would use `context.deck` and
  `context.event`/`context.current_stack_id` the same way `set_title.py` or
  `add_label.py` do.

Raise a normal exception for anything that goes wrong - don't catch it
yourself. One failing step is logged and recorded as failed by the engine
without aborting the rest of the workflow; see "Fault tolerance" in
automation/README.md.

No registration step exists or is needed - dropping the file into
`actions_registry/` *is* the registration. `ModuleLoader` discovers every
`WorkflowAction` subclass in that directory automatically the next time
anything imports it.

## 2. Verify it's discovered

```bash
python -m automation.main --list-modules
```

This prints every currently loadable module as JSON, including its
`default_input()`/`default_output()`. Your new module should be in the
list:

```json
{
  "name": "uppercase_text",
  "requires": [],
  "input": {"text": ""},
  "output": {"text": ""}
}
```

If it's missing, check the log output on stderr - a broken module (import
error, syntax error) is skipped and logged rather than crashing the whole
registry, so the reason is usually right there.

## 3. Write a test

Not required for the module to work, but is how every shipped module in
this repo is verified - see `automation/tests/` for more examples (e.g.
`test_date_offset.py` for another module with no Nextcloud dependency,
`test_generate_random_number.py` for one that uses a port).
Create `automation/tests/test_uppercase_text.py`:

```python
from __future__ import annotations

from automation.actions_registry.uppercase_text import UppercaseTextAction
from automation.core.domain.models import DeckEvent, EventType
from automation.core.ports.action_module import ActionContext
from automation.testing.fakes import InMemoryActionRegistry, InMemoryDeckGateway


def make_context() -> ActionContext:
    return ActionContext(
        event=DeckEvent(instance="test", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10),
        deck=InMemoryDeckGateway(),
        modules=InMemoryActionRegistry({}),
    )


def test_converts_text_to_upper_case():
    output = UppercaseTextAction().execute(make_context(), {"text": "hello"})

    assert output == {"text": "HELLO"}
```

Run it (from the repo root, with the dev virtualenv active):

```bash
python -m pytest automation/tests/test_uppercase_text.py -v
```

## 4. Activate it: make it usable in a workflow

"Activating" a module just means making its current shape visible to
whatever builds workflows that reference it - there's no separate
enable/disable switch.

- **On the server/cron side**, nothing further is needed: the moment the
  file exists, every subsequent `python -m automation.main` run (any mode)
  can resolve `uppercase_text` as a step's `module:`.
- **For the website's builder** (`website/new.php`) to offer it in the
  module dropdown and render its `text` field, it reads
  `automation/var/modules.json` - a snapshot written automatically by
  *every* `python -m automation.main` invocation, including `--list-modules`
  and `--dry-run`. So right after step 2 above, that snapshot is already
  up to date; the next time anyone opens the website's "Neuer Workflow"
  page, `uppercase_text` shows up in the list, with a `text` input
  rendered automatically from `default_input()`.
- **Using it directly in a workflow YAML** (`workflows/<id>.yaml`, whether
  written by hand or by the website) just needs a step like:

  ```yaml
  actions:
    - id: shout
      module: uppercase_text
      params:
        text: "hello from a workflow"
    - module: log_action
      params:
        message: {$ref: shout.text}   # -> "HELLO FROM A WORKFLOW"
  ```

That's the whole lifecycle: write the file, it's discovered, it's
available everywhere a module can be referenced.

## Going further

- **A module that calls another module**: declare `REQUIRES = ("other_action",)`
  and call `context.modules.get("other_action").execute(context, {...})` -
  see "Modules calling modules" in automation/README.md.
- **A module with its own persistent state** (like
  `generate_random_number`'s "already generated" list): add a method to
  `SqliteStateStore` behind a small port in `core/ports/`, give
  `ActionContext` a new optional field for it, and thread it through
  `WorkflowEngine`/`main.py` - see `core/ports/sequence_store.py` and how
  `generate_random_number.py` uses `context.sequence_store` for a worked
  example of that pattern.
- **Picking a good default-input shape**: the *type* of each field in
  `default_input()` (string, number, boolean, `null`, object) is what the
  website uses to decide which kind of input control to render for it -
  keep the example value representative of the real type you expect.
