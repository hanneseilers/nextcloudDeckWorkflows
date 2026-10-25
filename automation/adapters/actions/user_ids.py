"""Shared by assign_user / unassign_user: the `user_id` param may name one or
several assignees - users, and groups (Deck can assign a Nextcloud group to a
card as a whole).

An assignee is written as a token: a plain user id (`anna`), or `group:<id>`
for a group (`group:foerderkreis`). Nextcloud user ids can't contain a colon,
so a token never mixes up a user with a group of the same name."""

from __future__ import annotations

import re
from typing import Any

# Nextcloud user ids may contain spaces, so only these separate several ids.
_SEPARATORS = re.compile(r"[,;\n]")

# Deck's participant types (Acl::PERMISSION_TYPE_*): the type goes to the API as
# the `type` of assignUser/unassignUser, the token prefix is how it is written.
TYPE_USER, TYPE_GROUP, TYPE_REMOTE, TYPE_CIRCLE = 0, 1, 6, 7
_PREFIXES = {TYPE_GROUP: "group:", TYPE_CIRCLE: "circle:", TYPE_REMOTE: "remote:"}


def token_of(participant_id: str, participant_type: int) -> str:
    """`anna`, `group:foerderkreis`, ... for a participant of a card."""

    return _PREFIXES.get(participant_type, "") + participant_id


def participant_of(token: str) -> tuple[str, int]:
    """The inverse of token_of: (id, Deck participant type)."""

    for participant_type, prefix in _PREFIXES.items():
        if token.lower().startswith(prefix):
            return token[len(prefix):].strip(), participant_type
    return token, TYPE_USER


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
