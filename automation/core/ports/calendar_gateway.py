from __future__ import annotations

from typing import Any, Optional, Protocol


class CalendarGatewayPort(Protocol):
    """Read-only Nextcloud Calendar (CalDAV) access for calendar_lookup."""

    def list_calendars(self) -> list[dict[str, Any]]: ...

    def find_next_occurrence(self, calendar_id: str, title_contains: str) -> Optional[dict[str, Any]]: ...
