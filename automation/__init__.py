"""Nextcloud Deck Workflows automation package."""

import sys as _sys
from pathlib import Path as _Path

# tools/build.sh may have bundled dependencies (PyYAML, requests, icalendar,
# python-dateutil) into automation/vendor/ for hosts with no working pip -
# same idea as website/vendor/ via Composer. Put it ahead of everything else
# on sys.path so it's used if present; harmless no-op otherwise (e.g. a dev
# checkout with its own venv, where these imports resolve normally).
_vendor_dir = _Path(__file__).resolve().parent / "vendor"
if _vendor_dir.is_dir():
    _sys.path.insert(0, str(_vendor_dir))
del _sys, _Path, _vendor_dir
