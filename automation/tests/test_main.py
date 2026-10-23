from __future__ import annotations

import json

from automation.main import _modules_snapshot, _write_modules_snapshot


def test_modules_snapshot_describes_every_registered_module():
    snapshot = _modules_snapshot()

    names = {module["name"] for module in snapshot["modules"]}
    assert {"send_email", "calendar_lookup", "set_title", "move_card"} <= names

    send_email = next(m for m in snapshot["modules"] if m["name"] == "send_email")
    assert send_email["input"] == {
        "to": "", "subject": "", "body": "", "template": None, "template_data": {},
        "dedupe_minutes": 15,
    }
    assert send_email["output"] == {"sent": True}
    assert send_email["requires"] == []


def test_snapshot_is_json_serializable():
    # website/src/ModuleRegistry.php just json_decode()s this file - guard against
    # any module's default_input()/default_output() accidentally returning something
    # that isn't plain JSON-safe data.
    json.dumps(_modules_snapshot())


def test_write_modules_snapshot_writes_valid_json(tmp_path):
    path = tmp_path / "nested" / "modules.json"

    _write_modules_snapshot(path)

    data = json.loads(path.read_text())
    assert "modules" in data
    assert len(data["modules"]) > 0


def test_write_modules_snapshot_does_not_raise_if_the_path_is_unwritable(tmp_path):
    # A file where a directory is expected - path.parent.mkdir() will fail.
    blocking_file = tmp_path / "blocked"
    blocking_file.write_text("")
    path = blocking_file / "modules.json"

    _write_modules_snapshot(path)  # must not raise
