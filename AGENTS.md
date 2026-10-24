# AGENTS.md

Operational notes for an AI coding agent working in this repo. For what
the project *does*, see [README.md](README.md); for a user-facing
tutorial, [TUTORIAL.md](TUTORIAL.md); for adding a new action module,
[MODULE_GUIDE.md](MODULE_GUIDE.md); for not-yet-built ideas,
[ROADMAP.md](ROADMAP.md). `automation/README.md` and `website/README.md`
are the detailed per-component references - read those before changing
anything non-trivial in either.

## What this is

Workflow automation for Nextcloud Deck, built to run on shared webspace:

- `automation/` - a Python script (`main.py`), invoked periodically via
  cron, that polls Nextcloud's Deck API, detects changes, and runs
  configured workflows. Hexagonal (ports & adapters) architecture.
- `website/` - a plain-PHP UI (no framework, no build step) for creating
  and managing workflows. Writes/reads the same `workflows/*.yaml` files
  and the same `automation/var/state.sqlite3` the Python side owns.
- `config/` - YAML config (`*.example.yaml` are templates; the real
  `*.yaml` files are gitignored, created locally or by `tools/install.sh`).
- `tools/build.sh` / `tools/install.sh` - package a deployable upload and
  guide a shared-hosting install. Not needed for local dev.

Both halves read/write the **same files** (`workflows/*.yaml`,
`automation/var/state.sqlite3`, `config/*.yaml`) - there is no API
between them, no shared process, and PHP never shells out to Python (it's
often disabled on shared hosting) or vice versa. If you need the website
to react to something Python computed, write it to one of those shared
files and have the other side read it - see `website/src/TestRunStore.php`
/`website/src/WebhookPingStore.php` for the established pattern (website
writes a request row, `main.py`'s next invocation picks it up).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -q -r automation/requirements-dev.txt
cd website && composer install
```

`requirements-dev.txt` pulls in `requirements.txt` plus `pytest` and
`cryptography` (the latter only needed for `automation/config/secrets.py`'s
tests - see "Known limitations" below for why it's dev-only).

## Running tests / checks

```bash
.venv/bin/python -m pytest -q              # automation/ - the only automated test suite
find website -name "*.php" -not -path "*/vendor/*" -print0 | xargs -0 -n1 php -l
node --check website/assets/builder.js website/assets/typeahead.js website/assets/test_run.js
```

There is **no PHPUnit** and **no JS test framework** in this project.
PHP's pure/stateless functions (e.g. `NextcloudApi::mapShareesResponse`,
`::mapPropfindCalendars`) are verified with small standalone PHP scripts
using `ReflectionMethod` to call the private static method directly and
assert on the result - write one of these (and run it, don't just write
it) rather than trusting a hand-trace for anything non-trivial. For
anything that touches the website end to end, start a real server
(`php -S localhost:PORT` from inside `website/`, pick an uncommon port)
and hit it with `curl` - this has repeatedly caught real bugs (most
recently two separate UTC-vs-local-timezone mismatches between Python and
PHP) that unit tests with fakes did not.

Always clean up after yourself in the repo root: `__pycache__/`,
`.pytest_cache/`, and any temp `config/nextcloud.yaml`/`settings.yaml`/
`automation/var/state.sqlite3`/`automation/var/modules.json` created for a
manual end-to-end test. None of those are tracked by git, but they do
confuse the *next* manual test run if left behind.

## Architecture notes

- `automation/core/domain/` - framework-free domain model
  (`Workflow`, `DeckEvent`, `WorkflowEngine`, pure logic like
  `schedule.should_fire`/`webhook_gate.should_poll_now`). No I/O here,
  ever - that's what makes it unit-testable with in-memory fakes
  (`automation/testing/fakes.py`).
- `automation/core/ports/` - Protocols the domain depends on.
  `automation/adapters/` - their real implementations (Nextcloud REST/CalDAV,
  SQLite, SMTP). `main.py` is the composition root; it's the only place
  that's allowed to wire a concrete adapter into the domain.
- `automation/actions_registry/` - one file per action capability, each a
  `WorkflowAction` subclass. Dropping a file in *is* the registration - no
  other code changes. See `MODULE_GUIDE.md` for a full walkthrough.
- `website/src/` - PSR-4 autoloaded (`NextcloudDeckWorkflows\`) PHP
  classes; the top-level `website/*.php` files are thin per-page scripts
  that use them. `website/assets/builder.js` drives the workflow-step
  tree editor; `website/assets/typeahead.js` is a small shared
  "type a name, pick from a dropdown" widget used by several pages.

## Conventions this codebase actually follows (not aspirational)

- **Degrade, don't crash.** One failing action must not abort the rest of
  a workflow; one failing workflow must not abort the rest of a run; one
  unreachable Nextcloud instance must not abort other instances. Every
  layer that fans out over several independent things wraps each one in
  its own `try`/`except` (or PHP `try`/`catch`), logs, and continues. Keep
  this pattern when adding new fan-out logic instead of letting one
  failure propagate.
- **No speculative abstraction.** Several refactors this project has done
  were explicitly triggered by a *third* real occurrence of the same
  shape appearing (e.g. the `api_*.php` endpoints, the card-editing action
  modules) - not predicted ahead of time. Three similar lines are fine;
  don't build a framework for a pattern that's only happened twice.
  Conversely, *do* extract once something is genuinely duplicated a third
  time - several such refactors are already in the git history as a
  model to follow.
- **Flag unverified assumptions explicitly.** Several things here are
  best-effort because no live Nextcloud instance was available while
  building them (see "Known limitations" below) - each one says so
  directly in its module docstring/README section, including what shape
  it assumes and what happens if that assumption is wrong. Keep doing
  this rather than presenting a guess as confirmed behavior.
- **Prefer a well-tested library over hand-rolled parsing/protocol
  logic** for anything non-trivial (PyYAML, `symfony/yaml`, `icalendar`+
  `python-dateutil` for CalDAV/RRULE, `cryptography`'s Fernet for
  encrypted secrets) - but see the vendoring note below before adding one
  to the Python side.
- **Python dependencies are vendored for shared hosting.**
  `tools/build.sh` bundles `automation/requirements.txt`'s packages into
  `automation/vendor/` (source-only, `--no-binary=:all:`) because shared
  hosts often have no working `pip`. A new *required* Python dependency
  must be pure-Python-vendorable the same way, or it breaks that story.
  An *optional* dependency (needed by one opt-in feature, like
  `cryptography` for encrypted app passwords) goes in
  `requirements-dev.txt` only, imported lazily inside the function that
  needs it, so everything else keeps working without it installed.
- **Timestamps that cross the Python/PHP boundary must be explicit UTC**
  on both sides (`datetime.now(timezone.utc)` in Python,
  `new DateTimeImmutable('now', new DateTimeZone('UTC'))` in PHP) - naive/
  local timestamps on one side and UTC on the other silently compare
  wrong instead of raising. This has been a real, repeated bug in this
  codebase; if you add a new timestamp that's written by one language and
  read by the other, test the comparison for real, not just that each
  side parses its own output.
- **`VERSION`** (project root) holds the tool's version, shown in the
  website's navigation - set it to the version of a new `versions/*` branch.
- **Don't merge `versions/*` branches, push, or amend published commits**
  without being explicitly asked - this project has gone through several
  version branches (`versions/v1.0.0` through the current one) and merges
  into `dev`/`main` have always been a separate, explicit step.

## Known limitations (best-effort, not verified against a live instance)

- `automation/adapters/nextcloud/event_source.py`'s `assignedUsers`/
  `labels` extraction (for `card_assigned`/`card_label_changed`).
- `automation/adapters/nextcloud/calendar_gateway.py` (CalDAV): no
  RDATE/RECURRENCE-ID support, only RRULE+EXDATE.
- `automation/actions_registry/add_checklist_item.py`: assumes Deck
  checklists are Markdown `- [ ]` lines in the card description (there's
  no separate checklist API).
- Webhooks (`website/webhook.php`): Nextcloud's actual outgoing-webhook
  behavior is unverified and configuring it is a Nextcloud-admin task
  outside this repo - which is exactly why polling remains the fallback
  rather than being removed. See `automation/README.md`'s "Webhooks"
  section for the full reasoning.

If you get access to a real Nextcloud instance, these are the places to
check first.
