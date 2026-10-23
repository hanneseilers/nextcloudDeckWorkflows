from __future__ import annotations

import sys
import threading
import time

from automation import main as main_module
from automation.adapters.run_lock import RunLock
from automation.config.settings import NextcloudInstanceConfig, Settings


def test_second_lock_on_the_same_file_fails_until_the_first_is_released(tmp_path):
    first, second = RunLock(tmp_path / "run.lock"), RunLock(tmp_path / "run.lock")

    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()


def test_acquire_can_wait_for_the_holder_to_finish(tmp_path):
    first, second = RunLock(tmp_path / "run.lock"), RunLock(tmp_path / "run.lock")
    first.acquire()
    threading.Timer(0.4, first.release).start()

    started = time.monotonic()
    assert second.acquire(wait_seconds=5) is True
    assert 0.3 < time.monotonic() - started < 3
    second.release()


def test_acquire_gives_up_after_the_wait_time(tmp_path):
    first, second = RunLock(tmp_path / "run.lock"), RunLock(tmp_path / "run.lock")
    first.acquire()
    assert second.acquire(wait_seconds=0.3) is False
    first.release()


def _settings(tmp_path):
    return Settings(
        workflows_dir=tmp_path / "wf", state_db_path=tmp_path / "var" / "state.sqlite3", log_level="INFO",
        instances={"p": NextcloudInstanceConfig("p", "https://x", "u", "pw")},
    )


def test_main_exits_without_running_while_another_run_holds_the_lock(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    ran = []
    monkeypatch.setattr(main_module, "load_settings", lambda config_dir=None: settings)
    monkeypatch.setattr(main_module, "run", lambda s: ran.append(s))
    monkeypatch.setattr(main_module, "_write_modules_snapshot", lambda path: None)
    monkeypatch.setattr(sys, "argv", ["main"])

    holder = RunLock(tmp_path / "var" / "run.lock")
    assert holder.acquire()
    main_module.main()
    assert ran == []  # skipped: someone else is running

    holder.release()
    main_module.main()
    assert ran == [settings]


def test_main_with_wait_lock_waits_for_the_running_process(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    ran = []
    monkeypatch.setattr(main_module, "load_settings", lambda config_dir=None: settings)
    monkeypatch.setattr(main_module, "run", lambda s: ran.append(s))
    monkeypatch.setattr(main_module, "_write_modules_snapshot", lambda path: None)
    monkeypatch.setattr(sys, "argv", ["main", "--wait-lock", "5"])

    holder = RunLock(tmp_path / "var" / "run.lock")
    holder.acquire()
    threading.Timer(0.4, holder.release).start()
    main_module.main()

    assert ran == [settings]
