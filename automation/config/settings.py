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
class Settings:
    workflows_dir: Path
    state_db_path: Path
    log_level: str
    instances: dict[str, NextcloudInstanceConfig]


def load_settings(config_dir: Optional[Path] = None) -> Settings:
    config_dir = Path(config_dir) if config_dir else REPO_ROOT / "config"

    general = _read_yaml(config_dir / "settings.yaml")
    nextcloud = _read_yaml(config_dir / "nextcloud.yaml")

    instances = {
        entry["name"]: NextcloudInstanceConfig(
            name=entry["name"],
            base_url=entry["url"].rstrip("/"),
            username=entry["username"],
            app_password=entry["app_password"],
        )
        for entry in nextcloud.get("instances", [])
    }

    return Settings(
        workflows_dir=REPO_ROOT / general.get("workflows_dir", "workflows"),
        state_db_path=REPO_ROOT / general.get("state_db_path", "automation/var/state.sqlite3"),
        log_level=general.get("log_level", "INFO"),
        instances=instances,
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing config file: {path} (copy the matching *.example.yaml and fill in your values)"
        )
    return yaml.safe_load(path.read_text()) or {}
