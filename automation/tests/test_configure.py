from __future__ import annotations

import pytest
import yaml

from automation.config import configure
from automation.config.settings import load_settings


class ScriptedIO:
    """Answers the dialog from a list; records everything said."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.said = []
        self.prompts = []

    def say(self, text=""):
        self.said.append(text)

    def ask(self, prompt):
        self.prompts.append(prompt)
        return self.answers.pop(0)

    secret = ask


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(configure, "CONFIG_DIR", tmp_path)
    return tmp_path


def test_examples_in_repo_match_the_schema():
    for name in configure.FILES:
        path = configure.REPO_ROOT / "config" / f"{name}.example.yaml"
        assert path.read_text(encoding="utf-8") == configure.example_text(name), (
            f"{path.name} is out of date - run: python -m automation.config.configure --write-examples"
        )


def test_example_files_are_loadable(tmp_path):
    for name in configure.FILES:
        (tmp_path / f"{name}.yaml").write_text(configure.example_text(name), encoding="utf-8")
    settings = load_settings(tmp_path)
    assert settings.public_url == "https://example.com/nextcloudDeckWorkflows/website"
    assert settings.max_run_seconds == 600
    assert settings.webhooks is not None and not settings.webhooks.enabled
    assert settings.error_notifications is not None and not settings.error_notifications.enabled
    assert list(settings.instances) == ["prod"]


def test_defaults_match_the_loader_fallbacks(tmp_path):
    """What an empty settings.yaml means must equal what the dialog proposes."""
    (tmp_path / "settings.yaml").write_text("{}\n")
    (tmp_path / "nextcloud.yaml").write_text("instances: []\n")
    loaded = load_settings(tmp_path)
    defaults = configure._defaults(configure.SETTINGS, False)
    assert loaded.max_run_seconds == defaults["max_run_seconds"]
    assert loaded.history_retention_days == defaults["history_retention_days"]
    assert loaded.timezone == defaults["timezone"]
    assert loaded.log_level == defaults["log_level"]
    assert loaded.public_url is None and defaults["public_url"] is None
    assert str(loaded.workflows_dir).endswith(defaults["workflows_dir"])
    assert str(loaded.state_db_path).endswith(defaults["state_db_path"])


def test_first_run_with_all_defaults_writes_complete_documented_files(config_dir):
    # settings: take every default (Enter), except public_url; switch nothing on.
    answers = [""] * 4 + ["https://x.example/ncdw/website/"] + [""] * 3  # up to history_retention_days
    answers += ["n"]  # error_notifications.enabled
    answers += ["n"]  # webhooks.enabled
    answers += ["j"]  # save?
    io = ScriptedIO(answers)
    values = configure.configure_fields(io, configure.SETTINGS, {}, False)
    assert values["public_url"] == "https://x.example/ncdw/website/"
    assert values["max_run_seconds"] == 600
    assert values["error_notifications"]["enabled"] is False
    configure.save(io, "settings", None, values, assume_yes=True)
    text = (config_dir / "settings.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert data["cron_interval_minutes"] == 240 and data["webhooks"]["enabled"] is False
    assert "# Zeitzone, in der die Website Zeiten anzeigt" in text  # every value is explained
    (config_dir / "nextcloud.yaml").write_text("instances: []\n")
    assert load_settings(config_dir).public_url == "https://x.example/ncdw/website"


def test_existing_values_are_offered_and_changes_listed(config_dir):
    (config_dir / "settings.yaml").write_text(configure.render("settings", {
        **configure._defaults(configure.SETTINGS, False), "max_run_seconds": 300,
    }), encoding="utf-8")
    current = configure._read(config_dir / "settings.yaml")
    io = ScriptedIO([""] * 5 + ["450"] + [""] * 3 + ["n", "n"])
    values = configure.configure_fields(io, configure.SETTINGS, current, False)
    assert values["max_run_seconds"] == 450
    assert values["cron_interval_minutes"] == 240
    assert any("[300]" in prompt for prompt in io.prompts)  # the existing value was the proposal
    assert not any("[NEU]" in line for line in io.said)  # nothing counts as new
    configure.save(io, "settings", current, values, assume_yes=True)
    assert any("max_run_seconds: 300 -> 450" in line for line in io.said)
    assert (config_dir / "settings.yaml.bak").exists()


def test_missing_only_asks_for_new_keys_and_keeps_the_rest(config_dir):
    old = {"workflows_dir": "wf", "log_level": "DEBUG"}
    (config_dir / "settings.yaml").write_text(yaml.safe_dump(old), encoding="utf-8")
    current = configure._read(config_dir / "settings.yaml")
    assert "public_url" in configure.missing_keys("settings", current)
    io = ScriptedIO([""] * 30 + ["n", "n"])
    values = configure.configure_fields(io, configure.SETTINGS, current, True)
    assert values["workflows_dir"] == "wf" and values["log_level"] == "DEBUG"
    asked = [p for p in io.prompts if p.startswith("  Wert")]
    assert not any("wf" in p for p in asked)
    assert values["timezone"] == "Europe/Berlin"


def test_validation_rejects_and_reasks(config_dir):
    field = next(f for f in configure.SETTINGS if f.key == "public_url")
    io = ScriptedIO(["example.com/x", "https://example.com/x"])
    assert configure.ask_field(io, field, None, True) == "https://example.com/x"
    assert any("http://" in line for line in io.said)
    int_field = next(f for f in configure.SETTINGS if f.key == "max_run_seconds")
    io = ScriptedIO(["abc", "0", "120"])
    assert configure.ask_field(io, int_field, 600, False) == 120


def test_optional_value_can_be_cleared(config_dir):
    field = next(f for f in configure.SETTINGS if f.key == "public_url")
    assert configure.ask_field(ScriptedIO(["-"]), field, "https://a.example", False) is None


def test_unknown_keys_survive_a_rewrite(config_dir):
    path = config_dir / "settings.yaml"
    path.write_text("workflows_dir: wf\nmy_custom_key: 7\n", encoding="utf-8")
    current = configure._read(path)
    values = {**configure._defaults(configure.SETTINGS, False), **current}
    configure.save(ScriptedIO([]), "settings", current, values, assume_yes=True)
    assert yaml.safe_load(path.read_text())["my_custom_key"] == 7


def test_nextcloud_first_instance_and_encrypted_password_kept(config_dir):
    io = ScriptedIO(["prod", "https://cloud.example.com", "bot", "secret", "n"])
    values = configure.configure_nextcloud(io, {}, False)
    assert values["instances"][0]["app_password"] == "secret"
    configure.save(io, "nextcloud", None, values, assume_yes=True)
    assert load_settings_instances(config_dir) == ["prod"]

    current = {"instances": [{"name": "a", "url": "https://c.example", "username": "u",
                              "encrypted_app_password": "gAAAA", "extra": 1}]}
    io = ScriptedIO([""] * 3 + [""] + ["n"])  # name, url, username, (password: Enter keeps), no more
    values = configure.configure_nextcloud(io, current, False)
    instance = values["instances"][0]
    assert instance["encrypted_app_password"] == "gAAAA" and "app_password" not in instance
    assert instance["extra"] == 1
    text = configure.render("nextcloud", values)
    assert "encrypted_app_password" in text and yaml.safe_load(text)["instances"][0]["extra"] == 1


def load_settings_instances(config_dir):
    (config_dir / "settings.yaml").write_text("{}\n")
    return list(load_settings(config_dir).instances)


def test_secrets_never_appear_in_the_change_summary(config_dir):
    io = ScriptedIO([])
    before = {"instances": [{"name": "a", "url": "u", "username": "x", "app_password": "OLD-SECRET"}]}
    after = {"instances": [{"name": "a", "url": "u", "username": "x", "app_password": "NEW-SECRET"}]}
    configure.save(io, "nextcloud", before, after, assume_yes=True)
    output = "\n".join(io.said)
    assert "OLD-SECRET" not in output and "NEW-SECRET" not in output and "(geändert)" in output


def test_get_prints_a_nested_value(config_dir, capsys):
    (config_dir / "settings.yaml").write_text("webhooks:\n  secret: abc\n")
    assert configure.main(["--get", "settings.webhooks.secret"]) == 0
    assert capsys.readouterr().out.strip() == "abc"


def test_webhook_secret_needs_a_minimum_length_and_no_placeholder(config_dir):
    field = next(f for f in configure.SETTINGS if isinstance(f, configure.Section) and f.key == "webhooks").fields[1]
    assert field.key == "secret"
    io = ScriptedIO(["kurz", "CHANGE_ME_TO_A_LONG_RANDOM_STRING", "x" * 24])
    assert configure.ask_field(io, field, "", True) == "x" * 24
    assert sum(line.strip().startswith(("Zu kurz", "Das ist der Platzhalter")) for line in io.said) == 2


def test_enabling_webhooks_proposes_a_generated_long_secret_and_https(config_dir):
    section = next(f for f in configure.SETTINGS if isinstance(f, configure.Section) and f.key == "webhooks")
    io = ScriptedIO(["j", "", "", "", ""])  # enabled, accept the generated secret, https default, fallback default
    values = configure._configure_section(io, section, None, False, "")
    assert len(values["secret"]) >= configure.MIN_WEBHOOK_SECRET_LENGTH
    assert values["require_https"] is True and values["enabled"] is True
    assert any("Vorschlag (neu erzeugt)" in line for line in io.said)


def test_min_secret_length_matches_the_website():
    php = (configure.REPO_ROOT / "website" / "src" / "Config.php").read_text(encoding="utf-8")
    assert f"MIN_WEBHOOK_SECRET_LENGTH = {configure.MIN_WEBHOOK_SECRET_LENGTH};" in php


def test_the_backup_has_the_same_permissions_as_the_original(config_dir):
    import os
    import stat

    path = config_dir / "settings.yaml"
    path.write_text("workflows_dir: wf\n")
    os.chmod(path, 0o640)
    current = configure._read(path)
    configure.save(ScriptedIO([]), "settings", current, {**configure._defaults(configure.SETTINGS, False), "workflows_dir": "x"}, assume_yes=True)
    backup = config_dir / "settings.yaml.bak"
    assert stat.S_IMODE(backup.stat().st_mode) == 0o640 and "workflows_dir: wf" in backup.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o640  # the rewritten file keeps its mode, too


def test_backups_are_not_committed():
    ignore = (configure.REPO_ROOT / ".gitignore").read_text()
    assert "config/*.yaml.bak" in ignore


def test_the_cron_rhythm_is_a_setting_with_a_four_hour_default():
    field = next(f for f in configure.SETTINGS if getattr(f, "key", "") == "cron_interval_minutes")
    assert field.default == 240 and field.kind == "int"
    assert not any(getattr(f, "key", "") == "health_stale_minutes" for f in configure.SETTINGS)


def test_the_retired_health_stale_minutes_is_dropped_when_the_file_is_rewritten(config_dir):
    path = config_dir / "settings.yaml"
    path.write_text("workflows_dir: wf\nhealth_stale_minutes: 40\nmy_custom_key: 7\n")
    assert "cron_interval_minutes" in configure.missing_keys("settings", configure._read(path))  # the new value is asked for

    io = ScriptedIO([""] * 40 + ["n", "n", "j"])
    assert configure.run(io, ["settings"], only_missing=True) == 0
    data = yaml.safe_load(path.read_text())
    assert "health_stale_minutes" not in data and data["cron_interval_minutes"] == 240
    assert data["my_custom_key"] == 7 and data["workflows_dir"] == "wf"  # everything else stays
    assert any("health_stale_minutes wird nicht mehr verwendet" in line for line in io.said)
