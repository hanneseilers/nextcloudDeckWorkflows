"""Shared by assign_user / unassign_user: the `user_id` param may name one user
or several."""

from __future__ import annotations

import re
from typing import Any

# Nextcloud user ids may contain spaces, so only these separate several ids.
_SEPARATORS = re.compile(r"[,;\n]")


def parse_user_ids(value: Any) -> list[str]:
    """One id, several ids separated by comma/semicolon/newline, or a list of
    ids -> the ids in order, trimmed, without empty entries or duplicates.
    Anything else (None, numbers, ...) yields no ids."""

    if isinstance(value, str):
        parts = _SEPARATORS.split(value)
    elif isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            parts.extend(_SEPARATORS.split(item) if isinstance(item, str) else [])
    else:
        return []
    ids: list[str] = []
    for part in parts:
        user_id = part.strip()
        if user_id and user_id not in ids:
            ids.append(user_id)
    return ids
