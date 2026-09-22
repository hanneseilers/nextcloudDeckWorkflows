# Nextcloud Deck Workflows

Workflow automation for the [Nextcloud Deck](https://apps.nextcloud.com/apps/deck) app. This project runs independently of Nextcloud and communicates with it exclusively through the Nextcloud and Deck REST APIs, so it can be deployed on any shared webspace without server-side Nextcloud app installation.

## How it works

- **website/** — A web UI for selecting a configured Nextcloud instance and its boards/decks, and defining automation workflows for them. See [website/README.md](website/README.md).
- **automation/** — A Python script that periodically executes the configured workflows in the background (e.g. via cron job). See [automation/README.md](automation/README.md).
- **workflows/** — Storage for the workflow definitions created via the website.
- **config/** — YAML configuration files (Nextcloud connections, credentials, general settings).

All configuration and workflow data is stored as YAML files, requiring no database.

## Requirements

- A shared webspace with PHP + Composer (for the website) and Python 3 (for the automation script)
- Access to a Nextcloud instance with the Deck app enabled
- Ability to schedule a recurring cron job

## Getting started

1. Configure your Nextcloud connection(s) in `config/`.
2. Use the website to create and manage workflows for your decks; workflows are saved as YAML files in `workflows/`.
3. Schedule `automation/` to run periodically via cron to execute the workflows in the background.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
