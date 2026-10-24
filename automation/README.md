# automation

Cron-driven workflow engine, built as a hexagonal (ports & adapters) architecture.

## Layout

- `core/domain/` — framework-free domain model (`Workflow`, `DeckEvent`, ...) and the `WorkflowEngine` application service. No I/O.
- `core/ports/` — abstract interfaces the core depends on (`WorkflowRepositoryPort`, `DeckGatewayPort`, `EventSourcePort`, `ActionModulePort`, `ExecutionLogPort`, `CalendarGatewayPort`, `SequenceStorePort`).
- `adapters/nextcloud/` — talks to the Nextcloud/Deck REST API; detects events by polling and diffing board state against the last snapshot (no webhooks needed). Also talks to Nextcloud Calendar over CalDAV (`calendar_gateway.py`, see below) using the same account/client as Deck.
- `adapters/persistence/` — `YamlWorkflowRepository` (workflow definitions as YAML in `workflows/`) and `SqliteStateStore` (snapshot + execution log + generate_random_number's used-number lists, `automation/var/state.sqlite3`).
- `adapters/actions/` — dynamically loads action modules from `actions_registry/`.
- `actions_registry/` — one file per action capability. Drop in a new file that subclasses `WorkflowAction` to add a capability; no other code needs to change. Ships with standard card-editing actions: `set_title`, `set_description`, `set_due_date`, `move_card`, `add_label`, `assign_user`, `unassign_user`, `add_comment`, `add_checklist_item` (Deck has no separate checklist API - this appends a `- [ ] text` Markdown line to the card's own description, which is how Deck represents checklists); `set_variable` (global workflow variables, see below); `date_offset` (today,
or any date, plus/minus N days - e.g. to compute a due date); `slice_text`
(extract the text between two delimiter strings); `extract_field` (pull a
value out of a dict/list by path - like `$ref` but also walks into lists by
index, e.g. "events.0.title"); `generate_random_number`/`forget_random_number`
(a unique random number generator with a persistent "already generated"
list, see "Random numbers" below); `format_text` ($placeholder substitution
from explicit values/`$ref`s into one string, for modules that don't do
their own substitution); `calculate` (add/subtract/multiply/divide two
numbers); `copy_card` (copies the card into a column of another board of the same instance - only title and description, optionally overridden; assignees, labels, due date etc. are not copied, see "Copying cards" below); `create_action_link` (a one-time link that runs any action for the current card, see "One-time action links" below); plus `send_email` (SMTP, own config, see below) and `calendar_lookup` (searches a Nextcloud calendar over CalDAV for the next occurrence of an event by title, see "Calendar lookup" below); plus `log_action` as a no-op reference/smoke-test action.
- `main.py` — cron entry point / composition root.

A workflow's `actions` is a list, run in order by the `WorkflowEngine` - a single event (e.g. "card created in stack X") can trigger several actions, such as moving the card and assigning a user and posting a comment. One failing action is logged and does not stop the rest of the chain from running.

## Trigger events

`EventType` (`core/domain/models.py`), detected by diffing each poll against
the last snapshot (`adapters/nextcloud/event_source.py`):

- `card_created`, `card_moved`, `card_deleted` - unambiguous, fire once each.
- `card_assigned` - a *new* user was added to the card's assignees (not a
  removal).
- `card_due_date_changed`, `card_description_changed` - that specific field's
  value differs from the last poll.
- `card_label_changed` - the card's set of labels differs from the last poll,
  either a label added or removed (unlike `card_assigned`, which only fires
  on an addition).
- `card_updated` - fires on *any* change to the card, including the specific
  ones above - it's a superset, not an alternative to them. A workflow can
  watch either the specific event it cares about, or `card_updated` to catch
  everything (e.g. a title or label change, which has no dedicated event).

A `Trigger`'s `stack_id` is optional - omitted (or "all columns" in the
website) means the workflow reacts to that event on any column of the board.

## Time-based (schedule) triggers

A workflow can run on a schedule instead of a Deck event - "every day at
09:00" or "every Monday at 09:00" - via `Trigger.schedule`
(`ScheduleTrigger`) instead of `event_type`:

```yaml
trigger:
  schedule:
    time: "09:00"          # HH:MM, server-local time (same as a cron expression)
    weekdays: [1, 2, 3, 4, 5]   # optional, ISO weekdays 1=Mon..7=Sun; omitted = every day
```

Checked once per `main.py` invocation (`_process_schedules`, independent of
the Deck-event polling below) via `core/domain/schedule.should_fire()`:
fires once the scheduled time for "today" has passed and hasn't already
fired for that slot (tracked in `state.sqlite3`'s `schedule_state` table) -
comparing against the last-fired timestamp rather than requiring an
exact-minute match, so a delayed or missed cron tick still fires on the
next one, and it never fires twice for the same slot.

A schedule-triggered run has no real triggering card, so `context.deck` is
a `NullDeckGateway` that raises a clear error if an action actually tries
to use it - stick to card-independent actions (`send_email`, `log_action`,
`generate_random_number`, `calculate`, `format_text`, ...). The website
still asks for an instance/board for a schedule-triggered workflow (same
`Workflow` shape either way), but nothing reads it unless an action calls
`context.deck` against it, so it only matters if you use one.

## Modules calling modules

An action can call another action module directly through `context.modules` (the
same `ActionModulePort` registry the engine itself uses):

```python
def execute(self, context: ActionContext, params: dict) -> None:
    appointment = context.modules.get("calendar_lookup").execute(
        context, {"calendar_id": "...", "title_contains": "Sync"}
    )
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

## Chaining a workflow's steps

Every action's input and output is a plain JSON object (dict). A step's output
can be fed into a *later* step's input via the workflow itself - no code needed
- by giving the step an `id` and referencing `<id>.<field>` from another step's
`params` with `{"$ref": "..."}`:

```yaml
actions:
  - id: lookup
    module: calendar_lookup
    params:
      calendar_id: "/remote.php/dav/calendars/alice/personal/"
      title_contains: "Team sync"
  - module: send_email          # no id needed - nothing references this step
    params:
      to: "team@example.com"
      subject: "Reminder"
      body: "$title at $start"
      template_data:
        title: {$ref: lookup.title}   # mapped from the lookup step's output
        start: {$ref: lookup.start}
```

A `$ref` can appear anywhere in `params`, including nested inside another dict
(like `template_data` above) or a list. Anything that isn't an exact
`{"$ref": "..."}` object - including a literal like `"fixed value"` or a plain
dict - is used as-is. A `$ref` to a step that hasn't run (wrong order), doesn't
exist, or produced no such field resolves to `None` and logs a warning rather
than raising - see `WorkflowEngine._resolve_ref` in `core/domain/engine.py`.

`card` is a reserved step id, always available without adding any step: it
holds the triggering card's raw Nextcloud fields, e.g. `{$ref: card.title}` or
`{$ref: card.duedate}` - whatever the Deck API returned for that card
(`title`, `description`, `duedate`, `labels`, `assignedUsers`, ...). Don't give
one of your own steps the id `card` - it would shadow this.

`vars` is a second reserved step id: the workflow's global variables, set via
the `set_variable` action (`{"name": "due_in_three_days", "value": {$ref: ...}}`)
under whatever name you choose. Read one back structurally with
`{$ref: vars.<name>}`, or - in actions that substitute text placeholders
(`send_email`, `add_comment`) - directly as `$<name>` in the text itself, with
no `$ref`/`template_data` wiring needed there at all.

This is the workflow-level counterpart to modules calling modules above: the
*workflow* wires one step's output into another step's input declaratively;
a *module's own code* decides when to call another module directly.

## If/else branching

A step can be a branch instead of a module call: `type: if` with a `condition`
and `then`/`else` lists of further steps (which can themselves contain `if`
steps - branches nest). Each side of the condition is a literal or a `$ref`,
resolved the same way as a module's params.

```yaml
actions:
  - type: if
    condition:
      left: {$ref: card.priority}
      op: eq
      right: high
    then:
      - module: add_label
        params: {label_id: 3}
    else:
      - module: log_action
        params: {message: "not urgent"}
  - module: log_action          # runs either way - outside the if
    params: {message: "always runs"}
```

`op` is one of `eq`, `ne`, `lt`, `gt`, `contains`, `beginswith`, `endswith`.
`eq`/`ne`/`lt`/`gt` compare numerically if both sides parse as numbers (so a
YAML int and a numeric-looking API string compare equal), otherwise as
strings for `lt`/`gt` and with plain equality for `eq`/`ne`; the other three
always compare as strings - see `WorkflowEngine._evaluate_condition`. A
condition that fails to evaluate takes the `else` branch and logs a warning
rather than crashing the workflow, consistent with everything else here.
Steps inside either branch can still be referenced via `$ref` by id from
anywhere else in the workflow, same as a top-level step.

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

## Re-running until nothing triggers

One workflow's own actions (move a card, change its due date, assign someone)
can be exactly what another workflow is watching for. So a single
`python -m automation.main` invocation doesn't poll just once: `run()` keeps
polling every configured board and re-running matching workflows for as long
as the *previous* pass triggered at least one of them, up to `max_run_seconds`
(`config/settings.yaml`, default 600s - keep it comfortably below your host's cron time limit, see "STRATO" below, and your cron
interval). Once a pass detects nothing new, or the time limit is hit, the run
ends; a limit hit just means "pick this up again next time", not an error.
Only the first pass polls every board; each later pass polls just the boards
that can have changed: those that had events in the previous pass and those an
action wrote to (`RecordingDeckGateway` notes them - e.g. `copy_card`'s target
board) - with many boards that saves most of the polling requests.

This only works safely because `PollingEventSource.poll()` doesn't save its new
snapshot by itself - `main.py` stores each card's new state (`advance()`) only
after all of that card's events have been handled, and commits the board's full
snapshot after the last one. See "If a run is killed" below for what that
means when the process dies in between.

### A workflow doesn't re-trigger itself

A workflow that changes a card makes the very next poll see that change as a
new event - which would match the same workflow again, and again. So within
one invocation each **(workflow, card, column)** combination runs at most
once (`WorkflowEngine.handle`); the memory is per run, so the next cron run
starts fresh and a later, genuinely new event runs normally. A *different*
workflow still runs for the changed card, and the same workflow still runs for
the card in a *different* column - which also ends a ping-pong between
workflows that move a card back and forth on its own (each combination runs
once). Test runs and one-time links are not subject to this rule.

Known trade-offs, kept on purpose to stay simple:

- A workflow whose own action moves the card to another column can run once
  more there (the new column is a new combination).
- A workflow that already ran for a card/column earlier in the same run is
  not triggered again by *another* workflow's later change of that card.
- A second, genuine change to the same card in the same column within one
  run (a person editing twice within the run) is picked up by the next run
  rather than the current one.

## If a run is killed (cron timeout)

Shared hosts often kill a cron job that runs too long and start it again
later. What the automation does about that:

- **One run at a time.** `main.py` takes an exclusive lock on
  `automation/var/run.lock`; a second invocation exits right away (the
  operating system drops the lock when a process dies, so a killed run never
  leaves a stale one). The immediate runs the website starts for webhooks and
  one-time links use `--wait-lock 120` instead: they wait for a running job to
  finish, so the ping/link is still handled.
- **Progress is saved card by card.** After all events of a card are handled,
  its new state is stored; a kill only repeats the card that was in flight,
  not the whole batch. Events are "at least once": the in-flight workflow may
  run its actions a second time.
- **The time budget is checked between events.** Once `max_run_seconds` has
  passed no new event is started (the rest is detected again next run - with
  webhooks enabled, the board is flagged so that run polls it even without a
  new ping). Set it
  comfortably below your host's limit - a single slow API call can still
  overrun it, and a run that is killed anyway is covered by the points above.
- **`send_email` doesn't repeat an email for the same event.** When a killed
  run is repeated, the identical email for the identical triggering change
  (same workflow, card, the card's state before the event, recipient, subject
  and body) is not sent again within `dedupe_minutes` (default 10080 = 7 days,
  0 = off). A new change on the card is a new event and sends normally; test
  runs, schedules and one-time links always send. The mail is remembered
  after it was sent, so a kill right after sending doesn't send it again. Other actions (comments, copies, ...) have no such
  guard; a kill in the middle of a workflow can run its earlier steps again.
- A one-time link left "running" by a kill is marked failed after 15 minutes
  instead of being re-run (see "One-time action links").
- A SIGTERM is not handled specially (no graceful shutdown); a hard SIGKILL
  couldn't be caught anyway.

## STRATO shared hosting: limits and settings

What STRATO documents for its hosting packages (as of the research for this
section - check your own package, the platform matters):

- **Cron jobs** are only available on STRATO's legacy platform, from "Hosting
  Plus" up, not on the new platform. Each job has a **runtime limit of 15
  minutes**; the control panel offers the intervals **once, daily, weekly,
  monthly** (a user report says hourly is possible on some packages - no
  5-minute cron). It is a best-effort service: delays of up to 4 hours are
  "normal", and only **one cron job per user runs at a time** (others wait).
  The command line is stored unencrypted, so don't put secrets in it.
- **PHP scripts** (the website): `max_execution_time` is 240 s for PHP
  7.2-8.3 (60 s CPU / 120 s for PHP up to 7.1); nothing is documented about
  `disable_functions` - whether `proc_open` works (needed for the immediate
  runs `webhook.php`/`link.php` start) has to be tried.
- Python: STRATO's FAQ doesn't mention it; user reports say SSH access exists
  and Python 3 with pip is installed (no sudo). Whether a cron job can start
  `python3` is not documented - test it.

What that means for the settings here (defaults changed accordingly):

- `max_run_seconds` (default **600**): below the 15-minute kill, leaving room
  for the event still running when the budget ends. With an hourly or daily
  cron there is no shorter interval to stay under.
- `health_stale_minutes`: raise it to the cron interval plus slack (e.g. 90
  for hourly, 1560 for daily), otherwise `health.php` reports the automation
  as stopped between runs.
- `dedupe_minutes` of `send_email` (default **10080 = 7 days**): a killed
  run is restarted at the next scheduled slot, hours or a day later - the
  window covers that. It only matches the very same event, so the long
  default doesn't swallow legitimate later emails.
- Reaction time is the cron interval (hours at worst), so on STRATO workflows
  react quickly only through the website's immediate runs (webhooks, one-time
  links) - if `proc_open` is available there. Otherwise they wait for the next
  cron run. A run killed at the 15-minute mark is covered by "If a run is
  killed" above.

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

## Random numbers

`generate_random_number` generates a random, digit-only number (leading
zeros allowed) that hasn't been generated before in the same named list -
e.g. for a unique ticket/ID number written onto a card.

```yaml
params:
  list_name: "tickets"   # independent workflows can use different lists (default "default")
  min_digits: 4          # starting/minimum width - "0042" at min_digits=4 (default 4)
  save: true             # record it so it won't be generated again (default true)
```

Output: `number` (string, zero-padded to its final width).

How it avoids repeats: the generated number is checked against (and, if
`save` is true, added to) a persistent list in `automation/var/state.sqlite3`
(`SequenceStorePort`, implemented by the same `SqliteStateStore` used for
polling snapshots and the execution log). If a draw at the current width
collides 5 times in a row, the width grows by one digit and the attempt
count resets - repeating until a free number is found. At realistic digit
counts this resolves in at most a handful of draws; growing the width by
one digit multiplies the available space by 10, so it converges fast even
once a list is fairly full.

`forget_random_number` removes a number from that list again - e.g. because
whatever was using it (a card, a ticket) was deleted, and the number should
become available to generate again:

```yaml
params:
  list_name: "tickets"
  number: "0042"   # typically {"$ref": "<step_id>.number"} from an earlier
                    # generate_random_number step, or any other module's output
```

Matching is by exact text, including leading zeros - not by numeric value.
Removing a number that was never saved (or already removed) is a no-op, not
an error.

## Calendar lookup

`calendar_lookup` (`actions_registry/calendar_lookup.py`) searches a Nextcloud
calendar over CalDAV for the next future occurrence of an event whose title
contains a given substring (case-insensitive) - recurring events included, so
a yearly "Birthday" or weekly "Standup" series resolves to its actual next
occurrence, not the series' original start date.

```yaml
params:
  calendar_id: "/remote.php/dav/calendars/alice/personal/"  # from list_calendars()
  title_contains: "Standup"   # "" matches any event
```

Output: `title`, `start`, `end`, `location` (all `null` if nothing matched).

How it works (`adapters/nextcloud/calendar_gateway.py`, `NextcloudCalendarGateway`):

- `list_calendars()` - `PROPFIND` on `/remote.php/dav/calendars/<user>/` (same
  account/`NextcloudClient` already used for Deck - no extra config needed).
- `find_next_occurrence()` - a `REPORT` (`calendar-query`) bounded to a
  two-year future time-range (CalDAV needs a bound to expand an open-ended
  RRULE), parsed with `icalendar`; the title filter is applied client-side
  (deliberately, not via CalDAV's server-side text-match, which is
  inconsistently supported and awkward against a recurring master where the
  title lives once for the whole series); each candidate's actual next
  occurrence is computed with `dateutil.rrule`, respecting `EXDATE`; the
  earliest matching occurrence overall wins.

**Not verified against a live Nextcloud instance** - built against the CalDAV
(RFC 4791) and iCalendar (RFC 5545) specs and Nextcloud's documented CalDAV
URL convention, but there was no live server available while building this.
Known limitations: `RDATE` (ad-hoc extra occurrences) and `RECURRENCE-ID`
(single-instance overrides of a recurring series) are not handled - only
`RRULE`+`EXDATE` on the series master. If something doesn't match a real
server's behaviour, `calendar_gateway.py` is the place to fix it.

With no calendar connection configured for an instance (e.g. the `--dry-run`
smoke test), `calendar_lookup` raises a clear error instead of crashing -
caught and logged like any other action's failure.

## Copying cards

`copy_card` creates a brand-new card in `target_stack_id` on `target_board_id`
(any board of the same Nextcloud instance, including the workflow's own).
The copy carries only a title and a description - assigned users, labels,
due date, comments and attachments are not copied. `title`/`description`
default to the original's current values (including changes earlier steps of
the same run made); a non-empty value replaces it in the copy. The original is
left untouched, and its output (`card_id`, `board_id`, `stack_id`) can be
`$ref`'d by later steps. The new card is an ordinary new card, so a workflow
triggered by "Karte erstellt" on the target board fires for it as well -
except the workflow that made the copy: it never reacts to its own copies, so
copying into the column it watches makes one copy, not an endless chain. A
copy of a copy is allowed up to 5 levels; beyond that `copy_card` fails (in
the history as a failed step), which cuts off a copy loop between two
workflows (A copies X to Y, B copies Y back to X).
The Deck API calls are not verified against a live Nextcloud instance.

## One-time action links

`create_action_link` creates a link such as
`https://example.com/website/link.php?h=<long random token>` that runs one
other action - for the card and workflow context it was created in - the
first time it is opened. Typical use: `create_action_link` → `set_variable`
(`name: linkurl`, `value: {$ref: <step>.url}`) → `add_comment`/`send_email`
with `$linkurl`, so someone can e.g. confirm or move a card with one click.

- **Setup:** `public_url` in `config/settings.yaml` (where `website/` lives),
  and `link.php` must be reachable without the site's Basic Auth - see
  `website/README.md`.
- **Params:** `action` (any action but `create_action_link` itself),
  `action_params` (its params; `$ref`s are resolved when the link is
  *created*, so they capture that moment), `success_message` (shown on
  success, empty = "Die Aktion wurde erfolgreich ausgeführt."),
  `valid_days` (days from creation the link can be used, 0/empty = no
  expiry; the step outputs `expires_at` (ISO, UTC) and `expires_text` -
  e.g. "31.10.2026 14:05" in the `timezone` from `config/settings.yaml` - to
  put into the email with the link; an expired link shows "abgelaufen" and
  unused expired links are deleted),
  `require_confirmation` (a GET only shows a "Jetzt ausführen" button - set
  this if the link may pass through chat/mail systems whose link-preview or
  virus-scanner bots would otherwise use it up by merely fetching it).
- **One-time:** only the SHA-256 of the token is stored. The first visit
  claims the link atomically; every later visit - even a concurrent one -
  sees "ungültig oder bereits verwendet". A failed action also uses the link
  up. Once run, the stored payload (params, card, variables) is wiped and
  finished links are purged after a day. Links that are never opened stay
  valid indefinitely.
- **Execution:** the website never runs Python, so `link.php` claims the link,
  asks for an immediate `python -m automation.main` run (best effort, same
  mechanism as `webhook.php`) and waits up to 25 s for the result: the page
  then shows the success text, or a generic error text (the real error is in
  the history, not on a page anyone holding the link can read). If the run
  can't be started (`proc_open` disabled), the page says the action was
  accepted and it runs with the next cron invocation.
- The run is recorded in the history under the workflow that created the link.
- If the process is killed while running a link (cron timeout), the link
  stays "running"; the next invocation marks one that has been running for
  more than 15 minutes as failed (history entry "Verarbeitung abgebrochen")
  instead of running it again - a rerun could execute the action twice.

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

## Webhooks (optional, polling remains the fallback)

Honest framing first: this project cannot verify Nextcloud Deck's actual
outgoing-webhook behavior (no live instance was available while building
this), and configuring Nextcloud to call out to an external URL is a
Nextcloud **server-admin** task (its own Flow/Webhooks settings) entirely
outside this codebase's control. So rather than guess at parsing whatever
Nextcloud sends in a webhook request body, `website/webhook.php` treats
an incoming call purely as a "check this board now" signal - the admin
bakes `instance`/`board_id` into the URL they configure in Nextcloud, and
the request body is ignored entirely:

```
https://your-site/website/webhook.php?secret=...&instance=prod&board_id=42
```

Enable it in `config/settings.yaml`:

```yaml
webhooks:
  enabled: true
  secret: "a-long-random-string"   # also put this in the URL Nextcloud calls
  fallback_poll_minutes: 15
```

Once enabled, `core/domain/webhook_gate.should_poll_now` changes how
`main.py` decides which boards to poll each run: a board is always polled
if it's never been polled before, or if it's been pinged since its last
poll - otherwise it's only polled every `fallback_poll_minutes`. **This is
deliberately not "webhooks instead of polling" in the strict sense** -
polling becomes the fallback rather than the primary mechanism, because
webhook delivery reliability from Nextcloud is exactly the part that
can't be verified here, and this project's standing principle (see
"Re-running until nothing triggers" above, and the at-least-once
execution-log guarantee) is to never silently stop noticing a change.
Leave `webhooks` out of `settings.yaml` entirely (the default) and
nothing here changes - every board is polled every run, exactly as before
this feature existed.

`webhook.php` also makes a best-effort attempt (`proc_open`, wrapped so a
failure never affects its own response) to trigger an immediate
`python -m automation.main` run instead of waiting for the next cron
tick - `proc_open`/`exec` are commonly disabled on shared hosting, so this
may silently do nothing; either way the ping itself is always recorded
correctly and picked up on the next regular cron invocation. See
`website/health.php` for a list of recently received pings, to confirm
Nextcloud's configuration is actually reaching this endpoint at all.

## Encrypted app passwords

Optional hardening for shared hosting (other accounts on the same machine
sometimes being able to read files they shouldn't via misconfigured
permissions): instead of a plaintext `app_password` in
`config/nextcloud.yaml`, an instance can have `encrypted_app_password`.

```bash
python -m automation.config.secrets generate-key      # writes config/secret.key once
python -m automation.config.secrets encrypt "the real app password"
```

Paste the printed value into `nextcloud.yaml` as `encrypted_app_password`
instead of `app_password`. Uses `cryptography`'s Fernet (AES-128-CBC +
HMAC-SHA256, authenticated) - deliberately **not** in `requirements.txt`
or vendored by `tools/build.sh` like the project's other dependencies,
since it has a compiled extension that can't be vendored as plain source;
install it yourself (`pip install cryptography`) only if you use this.
`website/src/Fernet.php` decrypts the exact same token format in pure PHP
(via `openssl`/`hash_hmac`, no extra PHP dependency) using the same
`config/secret.key` - keep that file's permissions tight and never commit
it (already gitignored).

## Failure notifications

Optional: email an admin address once a workflow has failed `threshold`
times in a row, via `error_notifications` in `config/settings.yaml`
(disabled unless this section is present - see
`config/settings.example.yaml`):

```yaml
error_notifications:
  enabled: true
  threshold: 3
  to: "admin@example.com"
```

Uses the same `config/smtp.yaml` as `send_email` - set that up too.
Checked once per `main.py` invocation (`_process_failure_notifications`),
against the `threshold` most recent runs of each enabled workflow
(`SqliteStateStore.recent_run_outcomes`, one entry per run - a run counts
as failed if *any* of its actions failed). Notifies exactly once per
failure streak - a `failure_notifications` row marks "already notified for
the current, still-unbroken streak", cleared the moment a run succeeds, so
a workflow that keeps flapping doesn't spam an email on every single tick,
but does get a fresh notification if it recovers and then fails that many
times again.

## Health check & statistics

`website/health.php` shows whether `main.py` is still running (via the
heartbeat above - stale after `health_stale_minutes` from `config/settings.yaml`,
default 15; raise it if your host starts the job less often, e.g. 90 for hourly)
and simple
run statistics for the last 24 hours, overall and per workflow. The history is
kept `history_retention_days` (default 90) and then deleted at the end of a
run, so the database doesn't grow forever.
`health.php?format=json` returns the same data as JSON with an HTTP status
code (200 healthy, 503 not) an external uptime monitor can check directly
without parsing HTML.

## Adding a new action module

Create `automation/actions_registry/<name>.py`:

```python
from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext

class MyAction(WorkflowAction):
    ACTION_NAME = "my_action"

    def default_input(self) -> dict:
        return {"some_field": ""}   # optional: document the expected input shape

    def default_output(self) -> dict:
        return {}   # optional: document what execute() returns, {} if nothing

    def execute(self, context: ActionContext, params: dict) -> dict:
        ...  # use context.event and context.deck (a DeckGatewayPort)
        return {}   # a JSON object - later steps can map fields from it via $ref
```

Reference it from a workflow YAML's `actions[].module` field. `default_input`/
`default_output` are optional (the base class defaults to `{}`, meaning "no
particular shape") but documenting them is what lets other modules and a future
website form know what a module accepts and produces.
