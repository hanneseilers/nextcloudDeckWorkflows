from __future__ import annotations

import pytest
import yaml

from automation.config import secrets
from automation.config.settings import load_settings

pytest.importorskip("cryptography", reason="optional dependency, see automation/config/secrets.py")


def write_config(config_dir, nextcloud_instances):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "nextcloud.yaml").write_text(yaml.safe_dump({"instances": nextcloud_instances}))
    (config_dir / "settings.yaml").write_text(yaml.safe_dump({}))


def test_plain_app_password_still_works(tmp_path):
    config_dir = tmp_path / "config"
    write_config(config_dir, [
        {"name": "prod", "url": "https://cloud.example.com", "username": "bot", "app_password": "plain-secret"},
    ])

    settings = load_settings(config_dir)

    assert settings.instances["prod"].app_password == "plain-secret"


def test_encrypted_app_password_is_decrypted(tmp_path, monkeypatch):
    key_path = tmp_path / "secret.key"
    monkeypatch.setattr(secrets, "SECRET_KEY_PATH", key_path)
    key_path.write_text(secrets.generate_key().decode("ascii"))
    ciphertext = secrets.encrypt("decrypted-secret")

    config_dir = tmp_path / "config"
    write_config(config_dir, [
        {"name": "prod", "url": "https://cloud.example.com", "username": "bot", "encrypted_app_password": ciphertext},
    ])

    settings = load_settings(config_dir)

    assert settings.instances["prod"].app_password == "decrypted-secret"
