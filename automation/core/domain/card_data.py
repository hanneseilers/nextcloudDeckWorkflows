"""Pure helpers for reading a Deck card's raw data (as the REST API returns it)."""

from __future__ import annotations

from typing import Any, Optional


def assigned_user_ids(card: Optional[dict[str, Any]]) -> list[str]:
    """Best-effort extraction of the assigned user ids from a Deck card's
    `assignedUsers`, in order and without duplicates. Not verified against a
    live Nextcloud instance - tries the participant-wrapped shape first, then
    a couple of flatter fallbacks, and simply yields no ids (never raises) if
    the shape doesn't match any of them, so a schema mismatch degrades to
    "nobody assigned" instead of crashing.
    """

    ids: list[str] = []
    for entry in (card or {}).get("assignedUsers") or []:
        if not isinstance(entry, dict):
            continue
        participant = entry.get("participant")
        if isinstance(participant, dict) and participant.get("uid"):
            found = str(participant["uid"])
        elif entry.get("uid"):
            found = str(entry["uid"])
        elif entry.get("id") is not None:
            found = str(entry["id"])
        else:
            continue
        if found not in ids:
            ids.append(found)
    return ids


_TOKEN_PREFIXES = {1: "group:", 7: "circle:", 6: "remote:"}  # Deck participant type -> token prefix


def assigned_participants(card: Optional[dict[str, Any]]) -> list[str]:
    """Everybody (and every group) assigned to the card, as tokens: `anna` for a
    user, `group:foerderkreis` for a group (see adapters/actions/user_ids.py) -
    in order, without duplicates. Best effort like assigned_user_ids: the type is
    read from the assignment itself or its participant (a user when missing), and
    anything that doesn't fit is skipped, never raised."""

    tokens: list[str] = []
    for entry in (card or {}).get("assignedUsers") or []:
        if not isinstance(entry, dict):
            continue
        participant = entry.get("participant") if isinstance(entry.get("participant"), dict) else {}
        found = participant.get("uid") or participant.get("primaryKey") or entry.get("uid") or entry.get("id")
        if found in (None, ""):
            continue
        raw_type = entry.get("type", participant.get("type", 0))
        participant_type = raw_type if isinstance(raw_type, int) and not isinstance(raw_type, bool) else 0
        token = _TOKEN_PREFIXES.get(participant_type, "") + str(found)
        if token not in tokens:
            tokens.append(token)
    return tokens


def card_label_ids(card: Optional[dict[str, Any]]) -> list[str]:
    """The ids (as text) of the labels on a Deck card's `labels` - dicts with an
    `id` as Deck returns them, or plain ids. Best effort like assigned_user_ids:
    anything unexpected is skipped, never raised."""

    ids: list[str] = []
    for entry in (card or {}).get("labels") or []:
        found = entry.get("id") if isinstance(entry, dict) else entry
        if isinstance(found, (int, str)) and not isinstance(found, bool) and str(found) not in ids:
            ids.append(str(found))
    return ids
