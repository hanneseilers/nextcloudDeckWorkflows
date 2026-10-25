# website

Plain PHP UI for building Nextcloud Deck workflows - reads/writes the exact
same files the `automation/` cron job uses, no database.

## Setup

```bash
cd website
composer install
```

Then either point your web server at this `website/` directory, or simply
upload the whole project into the domain's document root **or any
subdirectory of it** (e.g. `https://example.com/tools/deck/`): the project
root's `.htaccess` redirects `…/deck/` (and page names like `…/deck/history.php`)
to `…/deck/website/`, and refuses everything outside `website/` - code,
`config/`, the state database, docs (`.well-known/` stays reachable for
certificate renewals). It computes its own base path, so no `RewriteBase`
needs adjusting. Without `mod_rewrite`, the root `index.php` still redirects
to `website/`, and `config/`, `automation/`, `workflows/` and the project files
in the root are denied by their own `.htaccess`. All links inside the site
are relative, and the session cookie (`ncdw_session`) is scoped to the
`website/` folder, so other PHP apps on the same domain don't interfere.

**This site has no login of its own.** It's meant to be protected externally,
e.g. with `.htaccess` Basic Auth on the whole `website/` directory - anyone who
can reach it can create/enable/disable/delete workflows. `website/src/` (the
PHP classes) is already denied via its own `.htaccess`, but that's defense in
depth, not a substitute for protecting the site itself.

**Two pages have to be reachable without that login:** `link.php` (one-time
action links, see "One-time action links" in `automation/README.md` - the
long random token in the URL is its credential) and, if you use webhooks,
`webhook.php` (protected by its own `secret`, sent in the `X-Webhook-Secret`
header - see "Webhooks" in `automation/README.md`). With Basic Auth in
`website/.htaccess`, exempt them (Apache 2.4; not tested on every host):

```apache
<FilesMatch "^(link|webhook)\.php$">
    Require all granted
</FilesMatch>
```

## How it fits together

- Reads `config/nextcloud.yaml` and `config/settings.yaml` (`src/Config.php`) -
  the same files `automation/config/settings.py` reads. Nextcloud credentials
  are only ever used server-side (`src/NextcloudApi.php`, via cURL); they never
  reach the browser.
- **The module list is renewed after an update by the website itself.**
  `modules.json` carries a fingerprint of the modules' code
  (`code_fingerprint()` in `automation/adapters/actions/loader.py`;
  `ModuleRegistry::currentFingerprint()` computes the same hash in PHP).
  If it differs - or is missing, as in a file an older version wrote - the editor,
  the Doku page and `save.php` have `python -m automation.main --list-modules`
  started in the background (`AutomationRunner::refreshModules()`, best effort,
  at most every 30 s) and the editor shows a notice with a "Seite neu laden" link;
  `save.php` explains an "unknown module" that is only unknown to the old list.
  Without this a new field (or module) stayed invisible until the next cron run -
  hours, with a cron job every few hours.
- Reads the list of available action modules and their `default_input()`/
  `default_output()` shapes from `automation/var/modules.json`
  (`src/ModuleRegistry.php`) - written automatically by every
  `python -m automation.main` run (see `automation/main.py`). If that file
  doesn't exist yet, run `python -m automation.main --list-modules` once.
- **Log (`log.php`):** shows the automation's log without a console. `main.py`
  writes `automation/var/automation.log` itself (rotating, 1 MB x 4 files,
  independent of any cron redirect); the page reads only the end of the file,
  newest entry first, tracebacks stay with their ERROR line, coloured by level.
  Filters: file (the Automation-Log or `cron.log` - the cron job's console output,
  which also holds crashes before logging starts such as a missing Python
  package), level (all / warnings and errors / errors only), text search, 100/
  300/1000 entries, optional refresh every 5 s. Times are server time, as in
  the file. `tools/test_log_reader.php` is a standalone check of the reader.
- **Vorlagen (`templates.php`, `template_action.php`):** the editor for the text
  templates in `config/text_templates/*.txt` (`src/TemplateStore.php`): list on
  the left with how many workflows use each, editor on the right (optional
  subject for e-mails + text, live list of the `$placeholders`, warning before
  leaving with unsaved changes), rename (optionally updating the workflows that
  name it), delete (refused while a workflow uses it), a collapsible help box
  (open the first time, then as left). A save from a form that is outdated
  (another tab saved meanwhile) is refused and keeps the typed text; so does a
  failed create. The steps' "Textvorlage" dropdowns (send_email `template`,
  format_text/add_comment `text_template`) offer the same names; an "i" next to
  each shows the template in a window over the editor (`api_template.php`,
  read only; X, a click outside or Escape closes it). Writes are atomic,
  names can't reach outside the folder, files are LF/UTF-8/at most 100 KB. The old
  `config/email_templates/` is moved over on the first visit.
  `tools/test_template_store.php` is a standalone check of the store.
- **Boards (`boards.php`):** board inspection - pick a Nextcloud instance
  (preselected if there's only one), get its boards with ids (archived ones
  last, marked), click one for its columns (id, card count) and labels (id,
  colour). Live requests through `NextcloudApi`, each list fetched separately
  so one failing request still shows the others; errors are shown on the
  page. Useful for typing an id directly or checking that a label belongs
  to the workflow's board (labels are per board - another board's label id
  makes Deck answer "Label does not exist").
- **Folding:** every step and every Wenn/Sonst block has a fold button (▾/▸) in
  front; folded, only the header and a one-line summary of what the step is set
  to remain (`summarizeStep()`), "Alle einklappen / ausklappen" above the steps does
  all of them. It is only how the editor looks (`node.collapsed`) - not saved, not
  in the payload, and folding doesn't redraw the page. A failed save (an invalid
  field, an incomplete reference) unfolds the step that holds the problem, without
  a redraw, so the half-typed value is still there to be seen. The one-time link's
  up to three actions each fold their settings the same way.
  An opened, saved workflow starts with everything folded (steps, Wenn/Sonst
  blocks, the link's actions); a step you add, or a link action you pick, starts
  open.
- **Switching a step off:** the power button (⏻) in a step's or block's header
  switches it off and on. A switched-off step is striped, marked "deaktiviert -
  wird übersprungen", and saved as `enabled: false` (written only when off);
  the automation skips it. Picking a switched-off step's output in a reference
  shows a warning, as it delivers no value. The workflow overview marks such
  steps with "- aus".
- **"Einmal-Link erstellen"** takes up to three actions (first, second, third;
  the second appears once the first is chosen, the third after the second, and
  an empty one is simply left out) and shows each chosen action's fields right
  in the step - the same rows (pickers, "Wert übernehmen", date fields ...) the action
  has as a step of its own - instead of a JSON box. They are saved as the
  step's `action_params` object (`syncActionFields()` in `assets/builder.js`);
  keys the action doesn't declare (hand-written YAML) are kept, and picking
  another action starts from that action's defaults. If the action itself is
  taken from a reference, its fields are unknown and the JSON row stays.
  References inside the fields follow renamed steps like any other.
- **Form controls** (inputs, dropdowns, textareas) share one look through the
  `--control-*` variables at the top of `assets/style.css` (applied with a
  zero-specificity `:where()` rule), so filters, folder forms and the log page
  match the editor. The navigation has no "new workflow" button - workflows
  are created in the folder view ("Workflow hier anlegen").
- **Step ids** are assigned by the editor, not typed: `<module>_<n>` in run
  order across all if/else branches (`add_label_1`, `add_label_2`, ...),
  re-assigned on every add/remove/move/module change (`assignStepIds()` in
  `assets/builder.js`), so they're always unique. References in params,
  conditions and JSON values follow a renamed step; a reference to a removed
  step becomes `<id>-entfernt` (shown as "unbekannter Schritt") instead of
  silently pointing at the step that inherits its name. Older workflows are
  renamed the first time they're opened and saved - a reference to an id
  that was used twice resolves to the latest step before it, which is also
  what the engine did at run time. Hand-written YAML may still use any id;
  the step's "i" box shows its id.
- **Docs (`docs.php`):** reference of every step type from `modules.json`:
  description, input fields (real names as in the YAML / "Felder der
  Action", German label, help text, default value) and output fields - the
  same texts as a step's "i" box in the editor, plus the "Karte" fields
  (a copy of `CARD_FIELDS` in `assets/builder.js` - keep both in sync) and
  the trigger events. A client-side filter narrows it by step or field name.
  Boards and Docs open in a new tab from the navigation (`Layout::NEW_TAB`),
  so an open editor isn't left behind. In the editor, an "i" above the steps
  shows the same "Karte" fields (`CARD_FIELDS`) with their real names.
- **Test runs ("Testlauf"):** the website never runs Python itself, so a test
  run is written to the `test_runs` table and `start_test_run.php` immediately
  starts `python -m automation.main --test-run <id>` in the background
  (`AutomationRunner`, needs `proc_open` - see `tools/check_server.sh`). That
  mode processes only this one request - no board polling, no schedules - so
  the result is usually there within seconds; the page waits up to 20 s, then
  shows the outcome (or "läuft gerade …", refreshing itself). Where the process
  can't be started, the request just stays queued and the next cron run
  executes it. A request is claimed atomically, so it never runs twice, and one
  left "running" by a killed process fails after 15 minutes instead of rerunning.
- **Folders:** the overview navigates a real directory tree below `workflows/`
  (breadcrumb, subfolders with counts). Folders can be created, renamed, moved
  and deleted (only when empty - nothing is removed along with a folder) from
  the page; workflows can be created in a folder, moved between folders, and
  the editor has an "Ordner" dropdown. Folder names are plain (letters
  incl. umlauts, digits, space, `-`, `_`; up to 60 characters; at most 6 levels
  deep) - every path is validated in `WorkflowRepository::normalizeFolder`
  before touching the filesystem. A workflow's id stays unique across all
  folders (the file is always `<id>.yaml`), the automation reads the whole tree,
  hidden (`.name`) and symlinked folders are ignored. The folder is just where
  the file lies - it isn't stored in the YAML, so moving a workflow never
  changes its history. `tools/test_workflow_repository.php` is a standalone
  check of the repository.
- Reads/writes `workflows/**/*.yaml` (`src/WorkflowRepository.php`) in the exact
  schema `automation/adapters/persistence/yaml_workflow_repository.py` expects,
  including the `{"$ref": "<step_id>.<field>"}` output-to-input mapping
  convention from `automation/core/domain/engine.py`.

## Typeahead pickers

Anywhere a field refers to real Nextcloud data by id - board, column
("Spalte"/stack), a user or group (`assign_user`/`unassign_user`'s `user_id`; a group is
`group:<id>`, found by the same search - the Sharees API with `shareType` 0 and 1), a
calendar (`calendar_lookup`'s `calendar_id`) - the UI is a type-to-filter
field with a clickable dropdown (`renderTypeahead()` in
`assets/builder.js`), not a plain `<select>` or a raw id text box. Board/
stack/calendar lists are small and already fetched for the current
instance/board, so typing filters them client-side; user search instead
queries `api_users.php` per keystroke (debounced, ≥3 characters), since the
Nextcloud user list can be large. `instance` and `event` stay plain
`<select>`s - both are small, fixed, locally-known lists, not Nextcloud
data that needs looking up.

## Scope of this iteration

- **index.php**: list workflows, enable/disable, delete.
- **new.php**: create a workflow - pick instance/board/column, event, then chain
  action modules together (literal params or mapped from an earlier step's
  output).
- Editing an existing workflow's module chain is **not** included yet - delete
  and recreate it for now.
