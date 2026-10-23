from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

try:
    import fcntl
except ImportError:  # not POSIX: no locking available, runs may overlap as before
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class RunLock:
    """An exclusive lock so two `python -m automation.main` invocations never
    process the same events at the same time (cron starting again while the
    previous run is still going, or a webhook/link-triggered run on top of
    it). A flock on a file: the operating system releases it when the process
    ends - including when it is killed - so a dead run can never leave a stale
    lock behind."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._file: Optional[object] = None

    def acquire(self, wait_seconds: float = 0.0) -> bool:
        """True once the lock is held; False if another run holds it for the
        whole `wait_seconds` (0 = don't wait)."""

        if fcntl is None:
            logger.warning("File locking is unavailable on this platform - overlapping runs are possible")
            return True

        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._path, "a")
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._file = handle
                return True
            except OSError:
                if time.monotonic() >= deadline:
                    handle.close()
                    return False
                time.sleep(0.2)

    def release(self) -> None:
        if self._file is not None and fcntl is not None:
            try:
                fcntl.flock(self._file, fcntl.LOCK_UN)
            finally:
                self._file.close()
                self._file = None
