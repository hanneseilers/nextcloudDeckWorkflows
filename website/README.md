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
`webhook.php` (protected by its own `secret`). With Basic Auth in
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
- Reads the list of available action modules and their `default_input()`/
  `default_output()` shapes from `automation/var/modules.json`
  (`src/ModuleRegistry.php`) - written automatically by every
  `python -m automation.main` run (see `automation/main.py`). If that file
  doesn't exist yet, run `python -m automation.main --list-modules` once.
- Reads/writes `workflows/*.yaml` (`src/WorkflowRepository.php`) in the exact
  schema `automation/adapters/persistence/yaml_workflow_repository.py` expects,
  including the `{"$ref": "<step_id>.<field>"}` output-to-input mapping
  convention from `automation/core/domain/engine.py`.

## Typeahead pickers

Anywhere a field refers to real Nextcloud data by id - board, column
("Spalte"/stack), a user (`assign_user`/`unassign_user`'s `user_id`), a
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
