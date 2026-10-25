"""The date values every text can use: `$date`, `$day`, `$weekday` - in comments,
e-mails, "Text zusammensetzen" and the text templates - and the reference source
`now` (`{"$ref": "now.day"}`, "Wert übernehmen" > "Datum und Uhrzeit (jetzt)").

Computed when the step runs (so "Erledigt am $date" in a one-time link's comment
shows the time of the click, not of the link's creation), in the timezone from
settings.yaml (`timezone`). A variable or value with the same name wins over these.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

# Index = datetime.weekday(): the German names, independent of the server's locale.
WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")

# (name, what it is) - for the docs and the editor's field list.
DATE_FIELDS = (
    ("date", "Datum und Uhrzeit (TT.MM.JJJJ hh:mm)"),
    ("day", "Datum (TT.MM.JJJJ)"),
    ("weekday", "Wochentag"),
)


def date_values(timezone_name: str, now: Optional[datetime] = None) -> dict[str, str]:
    """{"date": "25.10.2026 14:05", "day": "25.10.2026", "weekday": "Sonntag"}.
    `now` is an aware moment (default: the current one); a timezone this system
    doesn't know (no tz database) falls back to UTC."""

    moment = now or datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        moment = moment.astimezone(ZoneInfo(timezone_name))
    except Exception:
        moment = moment.astimezone(timezone.utc)
    return {
        "date": moment.strftime("%d.%m.%Y %H:%M"),
        "day": moment.strftime("%d.%m.%Y"),
        "weekday": WEEKDAYS[moment.weekday()],
    }


def with_date_values(values: dict[str, Any], timezone_name: str, now: Optional[datetime] = None) -> dict[str, Any]:
    """`values` plus the date values - the given ones win on a name clash, so a
    variable called `day` still means what its author meant."""

    return {**date_values(timezone_name, now), **values}
