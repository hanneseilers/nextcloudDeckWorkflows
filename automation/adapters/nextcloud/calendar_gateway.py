"""Read-only Nextcloud Calendar (CalDAV) access: list calendars, and search a
calendar for the next future occurrence of an event whose title contains a
given substring - including recurring events (RRULE), skipping excluded
occurrences (EXDATE).

Not verified against a live Nextcloud instance - there was no such access
available while building this; it follows the CalDAV (RFC 4791) and
iCalendar (RFC 5545) specs and Nextcloud's documented CalDAV URL convention
(`/remote.php/dav/calendars/<user>/`). If something doesn't match a real
server's exact behaviour, this is the place to fix it.

Deliberately does not use CalDAV's server-side text-match filter for the
title search (support for it is inconsistent across CalDAV servers,
especially against a recurring event's master, where the SUMMARY lives once
for the whole series) - instead fetches everything in a bounded future
time-range (which CalDAV servers are expected to expand recurrences against
per RFC 4791 9.9) and filters client-side.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote, unquote, urlparse
from xml.etree import ElementTree as ET

from dateutil.rrule import rrulestr
from icalendar import Calendar

from automation.adapters.nextcloud.client import NextcloudClient

_DAV = "{DAV:}"
_CALDAV = "{urn:ietf:params:xml:ns:caldav}"

# How far into the future to look for an occurrence. CalDAV time-range
# filtering needs a bound (an unbounded RRULE can't otherwise be queried) -
# two years comfortably covers yearly-recurring events too.
_SEARCH_HORIZON = timedelta(days=730)


def _parse_xml(xml_text: str) -> ET.Element:
    """ElementTree on a server's answer, minus the one thing that makes it
    dangerous: a DOCTYPE (entity declarations are how "billion laughs" /
    entity-expansion bombs are built, and older expat versions don't defend
    against them). A real CalDAV answer never has one - it is refused, not
    parsed."""

    if "<!DOCTYPE" in xml_text[:4096].upper() or "<!ENTITY" in xml_text[:4096].upper():
        raise ValueError("The calendar server's answer contains a DOCTYPE/ENTITY declaration - refused")
    return ET.fromstring(xml_text)


class NextcloudCalendarGateway:
    """Implements CalendarGatewayPort against Nextcloud's CalDAV endpoint."""

    def __init__(self, client: NextcloudClient, username: str) -> None:
        self._client = client
        self._username = username
        # CalDAV addresses calendars by the Nextcloud user id - normally the
        # same as the login name configured here (not verified for setups
        # where people log in with their e-mail address instead).
        self._base_path = f"/remote.php/dav/calendars/{quote(username, safe='')}/"
        # A Nextcloud installed in a subdirectory (https://host/nextcloud)
        # returns hrefs including that prefix, while requests are sent to
        # base_url + path - so hrefs are stored relative to base_url.
        self._url_prefix = urlparse(getattr(client, "base_url", "")).path.rstrip("/")

    def _relative(self, href: str) -> str:
        """Turns a CalDAV href (absolute URL, server-absolute path, or an
        already relative path) into a path relative to the configured base
        URL. Also repairs calendar ids saved before this normalisation."""

        path = urlparse(href).path if "://" in href else href
        if self._url_prefix and path.startswith(self._url_prefix + "/"):
            path = path[len(self._url_prefix):]
        return path

    def list_calendars(self) -> list[dict[str, Any]]:
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:propfind xmlns:d="DAV:">'
            "<d:prop><d:displayname/><d:resourcetype/></d:prop>"
            "</d:propfind>"
        )
        xml_text = self._client.request_xml("PROPFIND", self._base_path, body=body, depth=1)
        root = _parse_xml(xml_text)

        calendars = []
        for response in root.findall(f"{_DAV}response"):
            href = self._relative(response.findtext(f"{_DAV}href") or "")
            if unquote(href).rstrip("/") == unquote(self._base_path).rstrip("/"):
                continue  # the calendar-home collection itself, not a calendar in it

            prop = _first_prop(response)
            if prop is None:
                continue
            resourcetype = prop.find(f"{_DAV}resourcetype")
            is_calendar = resourcetype is not None and resourcetype.find(f"{_CALDAV}calendar") is not None
            if not is_calendar:
                continue

            displayname = prop.findtext(f"{_DAV}displayname") or href.rstrip("/").rsplit("/", 1)[-1]
            calendars.append({"id": href, "title": displayname})
        return calendars

    def find_next_occurrence(self, calendar_id: str, title_contains: str) -> Optional[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        best: Optional[tuple[datetime, Any]] = None

        for vevent in self._search_vevents(calendar_id, now):
            summary = str(vevent.get("summary", ""))
            if title_contains and title_contains.lower() not in summary.lower():
                continue
            occurrence = _next_occurrence(vevent, now)
            if occurrence is None:
                continue
            if best is None or occurrence < best[0]:
                best = (occurrence, vevent)

        if best is None:
            return None

        occurrence, vevent = best
        dtstart = _as_aware(vevent.get("dtstart").dt)
        dtend_prop = vevent.get("dtend")
        end = None
        if dtend_prop is not None:
            duration = _as_aware(dtend_prop.dt) - dtstart
            end = occurrence + duration

        location = vevent.get("location")
        return {
            "title": str(vevent.get("summary", "")),
            "start": occurrence.isoformat(),
            "end": end.isoformat() if end else None,
            "location": str(location) if location else "",
        }

    def _search_vevents(self, calendar_id: str, now: datetime):
        start = now.strftime("%Y%m%dT%H%M%SZ")
        end = (now + _SEARCH_HORIZON).strftime("%Y%m%dT%H%M%SZ")
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            "<d:prop><c:calendar-data/></d:prop>"
            "<c:filter><c:comp-filter name=\"VCALENDAR\"><c:comp-filter name=\"VEVENT\">"
            f'<c:time-range start="{start}" end="{end}"/>'
            "</c:comp-filter></c:comp-filter></c:filter>"
            "</c:calendar-query>"
        )
        xml_text = self._client.request_xml("REPORT", self._relative(calendar_id), body=body, depth=1)
        root = _parse_xml(xml_text)

        for response in root.findall(f"{_DAV}response"):
            ics_text = response.findtext(f".//{_CALDAV}calendar-data")
            if not ics_text:
                continue
            try:
                calendar = Calendar.from_ical(ics_text)
            except ValueError:
                continue  # one malformed resource must not abort the whole search
            yield from calendar.walk("VEVENT")


def _first_prop(response: ET.Element) -> Optional[ET.Element]:
    propstat = response.find(f"{_DAV}propstat")
    return propstat.find(f"{_DAV}prop") if propstat is not None else None


def _as_aware(value: Any) -> datetime:
    """icalendar gives date (all-day) or datetime (naive or aware) - normalize
    to an aware UTC datetime so every comparison/arithmetic below is
    consistent."""

    if not isinstance(value, datetime):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _next_occurrence(vevent: Any, now: datetime) -> Optional[datetime]:
    dtstart = _as_aware(vevent.get("dtstart").dt)

    rrule_prop = vevent.get("rrule")
    if rrule_prop is None:
        return dtstart if dtstart >= now else None

    exdates: set[datetime] = set()
    exdate_prop = vevent.get("exdate")
    if exdate_prop is not None:
        entries = exdate_prop if isinstance(exdate_prop, list) else [exdate_prop]
        for entry in entries:
            for dt in entry.dts:
                exdates.add(_as_aware(dt.dt))

    rule = rrulestr(f"RRULE:{rrule_prop.to_ical().decode('utf-8')}", dtstart=dtstart)
    candidate = rule.after(now, inc=True)
    while candidate is not None and _as_aware(candidate) in exdates:
        candidate = rule.after(candidate, inc=False)
    return _as_aware(candidate) if candidate is not None else None
