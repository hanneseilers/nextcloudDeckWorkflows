"""Loads runtime settings from the top-level config/ directory (not this package)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class NextcloudInstanceConfig:
    name: str
    base_url: str
    username: str
    app_password: str


@dataclass(frozen=True)
class ErrorNotificationConfig:
    """If enabled, main.py emails `to` once a workflow has failed
    `threshold` times in a row (and once more after it recovers and fails
    that many times again) - see main.py::_process_failure_notifications."""

    enabled: bool
    threshold: int
    to: str


@dataclass(frozen=True)
class WebhookConfig:
    """If enabled, main.py only polls a board on every single invocation
    until it's been pinged at least once; after that, a board with no
    recent webhook ping is only polled every `fallback_poll_minutes` (a
    board that *was* pinged since its last poll is always polled right
    away). See core/domain/webhook_gate.should_poll_now and
    website/webhook.php, which is what records a ping."""

    enabled: bool
    secret: str
    fallback_poll_minutes: float = 15.0


@dataclass(frozen=True)
class Settings:
    workflows_dir: Path
    state_db_path: Path
    log_level: str
    instances: dict[str, NextcloudInstanceConfig]
    # Upper bound (seconds) for how long one `main.py` run is allowed to keep
    # re-polling and re-running workflows in a row - see run()'s fixed-point
    # loop in main.py. Keep comfortably below the cron interval.
    max_run_seconds: float = 600.0
    error_notifications: Optional[ErrorNotificationConfig] = None
    webhooks: Optional[WebhookConfig] = None
    # Base URL the website is reachable at (e.g. https://example.com/deck/website),
    # used by create_action_link to build the links it hands out.
    public_url: Optional[str] = None
    # Execution history (website/history.php, failure notifications) older
    # than this is deleted at the end of each run.
    history_retention_days: float = 90.0


def load_settings(config_dir: Optional[Path] = None) -> Settings:
    config_dir = Path(config_dir) if config_dir else REPO_ROOT / "config"

    general = _read_yaml(config_dir / "settings.yaml")
    nextcloud = _read_yaml(config_dir / "nextcloud.yaml")

    instances = {
        entry["name"]: NextcloudInstanceConfig(
            name=entry["name"],
            base_url=entry["url"].rstrip("/"),
            username=entry["username"],
            app_password=_resolve_app_password(entry),
        )
        for entry in nextcloud.get("instances", [])
    }

    error_notifications = None
    raw_notifications = general.get("error_notifications")
    if raw_notifications:
        error_notifications = ErrorNotificationConfig(
            enabled=bool(raw_notifications.get("enabled", True)),
            threshold=int(raw_notifications.get("threshold", 3)),
            to=raw_notifications["to"],
        )

    webhooks = None
    raw_webhooks = general.get("webhooks")
    if raw_webhooks:
        webhooks = WebhookConfig(
            enabled=bool(raw_webhooks.get("enabled", True)),
            secret=raw_webhooks["secret"],
            fallback_poll_minutes=float(raw_webhooks.get("fallback_poll_minutes", 15.0)),
        )

    return Settings(
        workflows_dir=REPO_ROOT / general.get("workflows_dir", "workflows"),
        state_db_path=REPO_ROOT / general.get("state_db_path", "automation/var/state.sqlite3"),
        log_level=general.get("log_level", "INFO"),
        instances=instances,
        max_run_seconds=float(general.get("max_run_seconds", 600.0)),
        error_notifications=error_notifications,
        webhooks=webhooks,
        public_url=(str(general["public_url"]).rstrip("/") if general.get("public_url") else None),
        history_retention_days=float(general.get("history_retention_days", 90.0)),
    )


def _resolve_app_password(entry: dict[str, Any]) -> str:
    """A nextcloud.yaml instance entry has either `app_password` (plain) or
    `encrypted_app_password` (see automation/config/secrets.py) - never
    both in practice, but encrypted wins if somehow both are present, since
    that's the more deliberate choice."""

    if "encrypted_app_password" in entry:
        from automation.config.secrets import decrypt  # lazy: optional dependency

        return decrypt(entry["encrypted_app_password"])
    return entry["app_password"]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing config file: {path} (copy the matching *.example.yaml and fill in your values)"
        )
    return yaml.safe_load(path.read_text()) or {}
