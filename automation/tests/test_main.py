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
        "dedupe_minutes": 10080,
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


def test_setup_file_logging_writes_a_rotating_log_once(tmp_path):
    import logging
    from logging.handlers import RotatingFileHandler

    from automation.main import LOG_FILE_NAME, setup_file_logging

    root = logging.getLogger()
    before = list(root.handlers)
    try:
        path = setup_file_logging(tmp_path)
        assert path == tmp_path / LOG_FILE_NAME
        assert setup_file_logging(tmp_path) == path  # idempotent: still one handler for the file
        handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler) and h not in before]
        assert len(handlers) == 1 and handlers[0].maxBytes == 1_000_000 and handlers[0].backupCount == 3

        old_level = root.level
        root.setLevel(logging.INFO)
        logging.getLogger("automation.test").warning("hallo log")
        root.setLevel(old_level)
        line = path.read_text().strip().splitlines()[-1]
        assert " WARNING automation.test: hallo log" in line and line[:4].isdigit()
    finally:
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)
                handler.close()


def test_setup_file_logging_degrades_when_the_directory_is_not_writable(tmp_path):
    from automation.main import setup_file_logging

    blocker = tmp_path / "file"
    blocker.write_text("x")  # a file where the log directory should be
    assert setup_file_logging(blocker / "var") is None
