# website

Plain PHP UI for building Nextcloud Deck workflows - reads/writes the exact
same files the `automation/` cron job uses, no database.

## Setup

```bash
cd website
composer install
```

Then point your web server at this `website/` directory directly (no `public/`
subfolder - kept flat so it works on typical shared hosting without special
document-root configuration).

**This site has no login of its own.** It's meant to be protected externally,
e.g. with `.htaccess` Basic Auth on the whole `website/` directory - anyone who
can reach it can create/enable/disable/delete workflows. `website/src/` (the
PHP classes) is already denied via its own `.htaccess`, but that's defense in
depth, not a substitute for protecting the site itself.

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

## Scope of this iteration

- **index.php**: list workflows, enable/disable, delete.
- **new.php**: create a workflow - pick instance/board/column, event, then chain
  action modules together (literal params or mapped from an earlier step's
  output).
- Editing an existing workflow's module chain is **not** included yet - delete
  and recreate it for now.
