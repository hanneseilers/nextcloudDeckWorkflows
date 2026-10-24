# Nextcloud Deck Workflows

Workflow automation for the [Nextcloud Deck](https://apps.nextcloud.com/apps/deck) app. This project runs independently of Nextcloud and communicates with it exclusively through the Nextcloud and Deck REST APIs, so it can be deployed on any shared webspace without server-side Nextcloud app installation.

## How it works

- **website/** — A web UI for selecting a configured Nextcloud instance and its boards/decks, and defining automation workflows for them. See [website/README.md](website/README.md).
- **automation/** — A Python script that periodically executes the configured workflows in the background (e.g. via cron job). See [automation/README.md](automation/README.md).
- **workflows/** — Storage for the workflow definitions created via the website; they can be organized in real subfolders (managed in the website).
- **config/** — YAML configuration files (Nextcloud connections, credentials, general settings).

Want to add your own capability beyond the modules shipped here (e.g. a
new action a workflow can use)? See [MODULE_GUIDE.md](MODULE_GUIDE.md).

All configuration and workflow data is stored as YAML files, requiring no database.

## Requirements

- A shared webspace with PHP 8.4.27+ (for the website) and Python 3 (for the automation script)
- Access to a Nextcloud instance with the Deck app enabled
- Ability to schedule a recurring cron job

## Deploying to a shared webspace

The repository itself isn't directly uploadable (dev-only files, no `vendor/`, no real credentials). Two scripts in `tools/` handle that:

1. On your dev machine: `tools/build.sh` exports the current (or a given) git ref, strips developer-only files, bundles `website/vendor/` via Composer, and produces an upload-ready folder and `.zip`/`.tar.gz` in `build/upload/`.
2. Upload that folder/archive to your webspace - into the domain's document root or any subdirectory (e.g. `/tools/deck/`); the included `.htaccess` sends visitors on to `website/` and blocks everything else (see `website/README.md`).
3. On the server, inside the uploaded directory: run `./install.sh` - it walks you through PHP/Python dependencies, runs `./configure.sh` (see below) to write `config/*.yaml`, optionally sets up HTTP Basic Auth for `website/`, checks write permissions, offers to add the cron job, and verifies everything at the end.

### Configuration: `configure.sh`

`./configure.sh` (in the upload folder; `tools/configure.sh` in the repository) reads `config/nextcloud.yaml`, `settings.yaml` and `smtp.yaml` and goes through every value: what is already set is offered for adoption (Enter), what is missing is proposed with its default and marked `[NEU]`. The files are always written complete - every value with a comment saying what it is for, including the optional sections (`error_notifications`, `webhooks`, written with `enabled: false`) - and the previous file is kept as `*.yaml.bak`. `install.sh` uses it for its configuration step, so a first install proposes all defaults.

```bash
./configure.sh                            # all files
./configure.sh settings                   # one file (nextcloud | settings | smtp)
./configure.sh --missing                  # only values a newer version added
./configure.sh --get settings.public_url  # print one value
```

The `config/*.example.yaml` templates are generated from the same definition (`python -m automation.config.configure --write-examples`); a test fails if they drift apart.

## Getting started (manual / development setup)

1. Configure your Nextcloud connection(s): `tools/configure.sh`, or copy the `config/*.example.yaml` files by hand.
2. Use the website to create and manage workflows for your decks; workflows are saved as YAML files in `workflows/`.
3. Schedule `automation/` to run periodically via cron to execute the workflows in the background.

New to building workflows here? [TUTORIAL.md](TUTORIAL.md) (German) walks
through using the tool from first principles to a multi-step example.
Looking for ideas on what to build next? See [ROADMAP.md](ROADMAP.md)
(German) for a curated list of not-yet-implemented features.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
