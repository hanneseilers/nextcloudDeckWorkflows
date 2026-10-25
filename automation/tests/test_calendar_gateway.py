from __future__ import annotations

from datetime import datetime, timedelta, timezone

from automation.adapters.nextcloud.calendar_gateway import NextcloudCalendarGateway

_FMT = "%Y%m%dT%H%M%SZ"


class _FakeCalDavClient:
    """Stand-in for NextcloudClient: returns canned XML per CalDAV method,
    ignoring the request body/depth (the gateway's own query construction
    isn't what these tests are checking)."""

    def __init__(self, propfind_xml: str = "", report_xml: str = "", base_url: str = "https://cloud.example") -> None:
        self._propfind_xml = propfind_xml
        self._report_xml = report_xml
        self.base_url = base_url
        self.paths: list[tuple[str, str]] = []

    def request_xml(self, method: str, path: str, body: str = "", depth=None) -> str:
        self.paths.append((method, path))
        if method == "PROPFIND":
            return self._propfind_xml
        if method == "REPORT":
            return self._report_xml
        raise AssertionError(f"unexpected CalDAV method: {method}")


def _propfind_response(base_path: str, calendars: list[tuple[str, str]]) -> str:
    entries = (
        f'<d:response><d:href>{base_path}</d:href><d:propstat><d:prop>'
        "<d:resourcetype><d:collection/></d:resourcetype>"
        "</d:prop></d:propstat></d:response>"
    )
    # A non-calendar child collection (e.g. a scheduling inbox) must be filtered out too.
    entries += (
        f'<d:response><d:href>{base_path}inbox/</d:href><d:propstat><d:prop>'
        "<d:displayname>Inbox</d:displayname>"
        "<d:resourcetype><d:collection/></d:resourcetype>"
        "</d:prop></d:propstat></d:response>"
    )
    for href, name in calendars:
        entries += (
            f'<d:response><d:href>{href}</d:href><d:propstat><d:prop>'
            f"<d:displayname>{name}</d:displayname>"
            "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
            "</d:prop></d:propstat></d:response>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        + entries +
        "</d:multistatus>"
    )


def _vevent(
    uid: str,
    summary: str,
    dtstart,
    dtend=None,
    rrule: str | None = None,
    exdate=None,
    location: str | None = None,
    all_day: bool = False,
) -> str:
    lines = ["BEGIN:VEVENT", f"UID:{uid}", f"SUMMARY:{summary}"]
    if all_day:
        lines.append(f"DTSTART;VALUE=DATE:{dtstart.strftime('%Y%m%d')}")
        if dtend is not None:
            lines.append(f"DTEND;VALUE=DATE:{dtend.strftime('%Y%m%d')}")
    else:
        lines.append(f"DTSTART:{dtstart.strftime(_FMT)}")
        if dtend is not None:
            lines.append(f"DTEND:{dtend.strftime(_FMT)}")
    if rrule:
        lines.append(f"RRULE:{rrule}")
    if exdate is not None:
        lines.append(f"EXDATE:{exdate.strftime(_FMT)}")
    if location:
        lines.append(f"LOCATION:{location}")
    lines.append("END:VEVENT")
    return "\r\n".join(lines) + "\r\n"


def _ics(*vevent_bodies: str) -> str:
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//test//EN\r\n"
        + "".join(vevent_bodies)
        + "END:VCALENDAR\r\n"
    )


def _report_response(*calendar_data_blocks: str) -> str:
    responses = "".join(
        "<d:response><d:href>/cal/evt.ics</d:href><d:propstat><d:prop>"
        f"<c:calendar-data>{block}</c:calendar-data>"
        "</d:prop></d:propstat></d:response>"
        for block in calendar_data_blocks
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        + responses +
        "</d:multistatus>"
    )


def _gateway(report_xml: str = "", propfind_xml: str = "") -> NextcloudCalendarGateway:
    client = _FakeCalDavClient(propfind_xml=propfind_xml, report_xml=report_xml)
    return NextcloudCalendarGateway(client, "alice")


def test_list_calendars_filters_out_the_home_collection_and_non_calendar_children():
    base_path = "/remote.php/dav/calendars/alice/"
    xml = _propfind_response(
        base_path,
        [(f"{base_path}personal/", "Personal"), (f"{base_path}work/", "Work")],
    )
    gateway = _gateway(propfind_xml=xml)

    result = gateway.list_calendars()

    assert result == [
        {"id": f"{base_path}personal/", "title": "Personal"},
        {"id": f"{base_path}work/", "title": "Work"},
    ]


def test_find_next_occurrence_matches_title_case_insensitively():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    dtstart = now + timedelta(days=5)
    dtend = dtstart + timedelta(hours=1)
    xml = _report_response(
        _ics(_vevent("evt1", "Team Sync Meeting", dtstart, dtend, location="Room 42"))
    )
    gateway = _gateway(report_xml=xml)

    result = gateway.find_next_occurrence("/cal/personal/", "sync")

    assert result["title"] == "Team Sync Meeting"
    assert datetime.fromisoformat(result["start"]) == dtstart
    assert datetime.fromisoformat(result["end"]) == dtend
    assert result["location"] == "Room 42"


def test_find_next_occurrence_returns_none_when_title_does_not_match():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    xml = _report_response(_ics(_vevent("evt1", "Team Sync Meeting", now + timedelta(days=5))))
    gateway = _gateway(report_xml=xml)

    assert gateway.find_next_occurrence("/cal/personal/", "retro") is None


def test_find_next_occurrence_computes_next_occurrence_of_a_recurring_event():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    dtstart = now - timedelta(days=100)

    days_elapsed = (now - dtstart).days
    first_candidate = dtstart + timedelta(days=days_elapsed)
    if first_candidate < now:
        first_candidate += timedelta(days=1)
    second_candidate = first_candidate + timedelta(days=1)

    xml = _report_response(
        _ics(_vevent("evt1", "Daily Standup", dtstart, rrule="FREQ=DAILY", exdate=first_candidate))
    )
    gateway = _gateway(report_xml=xml)

    result = gateway.find_next_occurrence("/cal/personal/", "")

    assert datetime.fromisoformat(result["start"]) == second_candidate


def test_find_next_occurrence_picks_the_earliest_among_several_matches():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    later = now + timedelta(days=10)
    sooner = now + timedelta(days=2)
    xml = _report_response(
        _ics(
            _vevent("evt1", "Planning Meeting", later),
            _vevent("evt2", "Kickoff Meeting", sooner),
        )
    )
    gateway = _gateway(report_xml=xml)

    result = gateway.find_next_occurrence("/cal/personal/", "meeting")

    assert result["title"] == "Kickoff Meeting"
    assert datetime.fromisoformat(result["start"]) == sooner


def test_find_next_occurrence_handles_all_day_events():
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    event_date = today + timedelta(days=10)
    xml = _report_response(_ics(_vevent("evt1", "Conference", event_date, all_day=True)))
    gateway = _gateway(report_xml=xml)

    result = gateway.find_next_occurrence("/cal/personal/", "conference")

    assert result["title"] == "Conference"
    assert datetime.fromisoformat(result["start"]) == event_date
    assert result["end"] is None


def test_find_next_occurrence_skips_a_malformed_calendar_data_block():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    xml = _report_response(
        "not a valid ics document at all",
        _ics(_vevent("evt1", "Team Sync Meeting", now + timedelta(days=5))),
    )
    gateway = _gateway(report_xml=xml)

    result = gateway.find_next_occurrence("/cal/personal/", "sync")

    assert result["title"] == "Team Sync Meeting"


def test_find_next_occurrence_returns_none_when_nothing_matches_the_time_range():
    xml = _report_response()
    gateway = _gateway(report_xml=xml)

    assert gateway.find_next_occurrence("/cal/personal/", "") is None


def test_nextcloud_in_a_subdirectory_hrefs_are_stored_relative_to_the_base_url():
    # The server answers with hrefs including the /nextcloud prefix; requests
    # go to base_url + path, so the prefix must not end up in there twice.
    served = "/nextcloud/remote.php/dav/calendars/alice/"
    xml = _propfind_response(served, [(f"{served}personal/", "Personal")])
    client = _FakeCalDavClient(propfind_xml=xml, report_xml="<d:multistatus xmlns:d=\"DAV:\"/>",
                               base_url="https://host.example/nextcloud")
    gateway = NextcloudCalendarGateway(client, "alice")

    assert gateway.list_calendars() == [
        {"id": "/remote.php/dav/calendars/alice/personal/", "title": "Personal"}
    ]
    # An id saved before the fix (with the prefix, or as a full URL) still works.
    gateway.find_next_occurrence(f"{served}personal/", "x")
    gateway.find_next_occurrence(f"https://host.example{served}personal/", "x")
    assert [p for m, p in client.paths if m == "REPORT"] == [
        "/remote.php/dav/calendars/alice/personal/"
    ] * 2


def test_user_name_is_url_encoded_in_the_calendar_home_path():
    client = _FakeCalDavClient(propfind_xml="<d:multistatus xmlns:d=\"DAV:\"/>")
    NextcloudCalendarGateway(client, "anna maier@example.org").list_calendars()
    assert client.paths == [("PROPFIND", "/remote.php/dav/calendars/anna%20maier%40example.org/")]


def test_an_answer_with_a_doctype_or_entities_is_refused_not_parsed():
    import pytest

    bomb = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>'
        '<d:multistatus xmlns:d="DAV:"><d:response>&lol2;</d:response></d:multistatus>'
    )
    gateway = _gateway(propfind_xml=bomb, report_xml=bomb)
    with pytest.raises(ValueError, match="DOCTYPE"):
        gateway.list_calendars()
    with pytest.raises(ValueError, match="DOCTYPE"):
        gateway.find_next_occurrence("/remote.php/dav/calendars/alice/personal/", "x")
