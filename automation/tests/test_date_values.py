from __future__ import annotations

from datetime import datetime, timezone

import pytest

from automation.actions_registry.add_comment import AddCommentAction
from automation.actions_registry.format_text import FormatTextAction
from automation.actions_registry.send_email import SendEmailAction
from automation.core.domain import date_values as date_values_module
from automation.core.domain.date_values import DATE_FIELDS, WEEKDAYS, date_values, with_date_values
from automation.tests.test_actions import make_context, make_deck

SUNDAY_NOON_UTC = datetime(2026, 10, 25, 12, 5, tzinfo=timezone.utc)  # a Sunday


def test_date_day_and_weekday_in_the_configured_timezone():
    # 25.10.2026 is the day the clocks go back in Germany: 12:05 UTC is 13:05 CET
    assert date_values("Europe/Berlin", SUNDAY_NOON_UTC) == {"date": "25.10.2026 13:05", "day": "25.10.2026", "weekday": "Sonntag"}
    assert date_values("UTC", SUNDAY_NOON_UTC)["date"] == "25.10.2026 12:05"
    assert date_values("America/Los_Angeles", SUNDAY_NOON_UTC)["date"] == "25.10.2026 05:05"


def test_the_day_follows_the_timezone_across_midnight():
    late = datetime(2026, 10, 24, 23, 30, tzinfo=timezone.utc)  # Saturday evening UTC, already Sunday in Berlin
    assert date_values("UTC", late)["weekday"] == "Samstag"
    # still summer time (+2) until 03:00 that night - the clocks go back at 25.10.2026 03:00 CEST
    assert date_values("Europe/Berlin", late) == {"date": "25.10.2026 01:30", "day": "25.10.2026", "weekday": "Sonntag"}


def test_all_seven_weekdays_are_german_whatever_the_servers_locale_is():
    names = [date_values("UTC", datetime(2026, 10, 19 + i, 8, 0, tzinfo=timezone.utc))["weekday"] for i in range(7)]  # Monday..Sunday
    assert names == list(WEEKDAYS) == ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def test_an_unknown_timezone_falls_back_to_utc_instead_of_failing():
    assert date_values("Nirgendwo/Atlantis", SUNDAY_NOON_UTC)["date"] == "25.10.2026 12:05"


def test_without_a_given_moment_it_is_now(monkeypatch):
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return SUNDAY_NOON_UTC

    monkeypatch.setattr(date_values_module, "datetime", Fixed)
    assert date_values("UTC")["day"] == "25.10.2026"


def test_the_documented_fields_are_exactly_the_ones_provided():
    assert [name for name, _ in DATE_FIELDS] == list(date_values("UTC", SUNDAY_NOON_UTC))


def test_a_variable_or_value_of_the_same_name_wins():
    merged = with_date_values({"day": "Dienstag", "name": "x"}, "UTC", SUNDAY_NOON_UTC)
    assert merged["day"] == "Dienstag" and merged["name"] == "x" and merged["weekday"] == "Sonntag"


# -- in the text actions ---------------------------------------------------------------------

def test_add_comment_fills_in_the_date_values():
    deck = make_deck()
    out = AddCommentAction().execute(make_context(deck), {"message": "Erledigt am $weekday, $day um $date."})
    today = date_values("Europe/Berlin")
    assert out["message"] == f"Erledigt am {today['weekday']}, {today['day']} um {today['date']}."
    assert "$" not in out["message"]


def test_add_comment_variable_named_like_a_date_value_wins():
    deck = make_deck()
    context = make_context(deck)
    context.variables["day"] = "mein Tag"
    assert AddCommentAction().execute(context, {"message": "$day / $weekday"})["message"].startswith("mein Tag / ")


def test_format_text_fills_in_the_date_values_and_values_win():
    out = FormatTextAction().execute(make_context(make_deck()), {"template": "$weekday: $titel ($day)", "values": {"titel": "T"}})
    today = date_values("Europe/Berlin")
    assert out == {"text": f"{today['weekday']}: T ({today['day']})"}
    assert FormatTextAction().execute(make_context(make_deck()), {"template": "$day", "values": {"day": "fix"}}) == {"text": "fix"}


def test_the_configured_timezone_of_the_context_is_used():
    context = make_context(make_deck())
    context.display_timezone = "UTC"
    assert AddCommentAction().execute(context, {"message": "$date"})["message"] == date_values("UTC")["date"]


def test_an_unknown_placeholder_is_still_left_as_it_is():
    assert AddCommentAction().execute(make_context(make_deck()), {"message": "$datum bleibt"})["message"] == "$datum bleibt"


# -- send_email: the subject, the text, and the duplicate guard --------------------------------------

@pytest.fixture
def smtp(monkeypatch, tmp_path):
    import yaml

    from automation.adapters import smtp_config as smtp_config_module
    from unittest.mock import MagicMock

    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.send_message.return_value = {}
    monkeypatch.setattr(smtp_config_module.smtplib, "SMTP", MagicMock(return_value=client))
    path = tmp_path / "smtp.yaml"
    path.write_text(yaml.safe_dump({"host": "h", "port": 25, "use_tls": False, "from_address": "bot@example.com"}))
    monkeypatch.setattr(smtp_config_module, "SMTP_CONFIG_PATH", path)
    return client


def test_send_email_fills_in_the_date_values_in_subject_and_text(smtp):
    SendEmailAction().execute(make_context(make_deck()), {"to": "a@example.com", "subject": "Bericht $day", "body": "Stand: $date ($weekday)"})
    sent = smtp.send_message.call_args[0][0]
    today = date_values("Europe/Berlin")
    assert sent["Subject"] == f"Bericht {today['day']}"
    assert sent.get_content().strip() == f"Stand: {today['date']} ({today['weekday']})"


def test_a_repeated_mail_is_still_recognised_although_the_time_in_it_changed(smtp, monkeypatch):
    """The guard compares the mail without the date values filled in: a killed run's
    rerun hours later has another time in the text, but is the same mail."""

    from automation.testing.fakes import InMemoryDuplicateGuard

    guard = InMemoryDuplicateGuard()
    context = make_context(make_deck())
    context.dedupe_store = guard
    params = {"to": "a@example.com", "subject": "S", "body": "Gesendet $date", "dedupe_minutes": 60}

    assert SendEmailAction().execute(context, params) == {"sent": True}
    values = iter([{"date": "25.10.2026 18:00", "day": "25.10.2026", "weekday": "Sonntag"}])
    monkeypatch.setattr("automation.actions_registry.send_email.with_date_values",
                        lambda data, tz, now=None: {**next(values, {"date": "LATER"}), **data})
    assert SendEmailAction().execute(context, params) == {"sent": False}  # the same mail, not sent twice
    assert smtp.send_message.call_count == 1


def test_the_editors_list_of_date_fields_is_the_one_of_the_automation():
    from pathlib import Path

    builder = (Path(__file__).resolve().parents[2] / "website" / "assets" / "builder.js").read_text(encoding="utf-8")
    block = builder[builder.index("const DATE_FIELDS = ["):]
    block = block[: block.index("];")]
    for name, label in DATE_FIELDS:
        assert f"['{name}', '{label}']" in block, (name, label)
    assert block.count("['") == len(DATE_FIELDS)
    templates_js = (Path(__file__).resolve().parents[2] / "website" / "assets" / "templates.js").read_text(encoding="utf-8")
    assert "const AUTOMATIC = [" + ", ".join(f"'{name}'" for name, _ in DATE_FIELDS) + "]" in templates_js


def test_the_now_reference_is_resolved_by_the_engine():
    from automation.core.domain.engine import _resolve_params

    today = date_values("Europe/Berlin")
    assert _resolve_params({"$ref": "now.day"}, {"now": today}) == today["day"]
    assert _resolve_params({"a": [{"$ref": "now.weekday"}]}, {"now": today}) == {"a": [today["weekday"]]}
