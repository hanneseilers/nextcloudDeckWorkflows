from __future__ import annotations

import pytest

from automation.actions_registry import send_email as send_email_module
from automation.actions_registry.add_comment import AddCommentAction
from automation.actions_registry.format_text import FormatTextAction
from automation.adapters import text_templates
from automation.adapters.text_templates import (
    NAME_PATTERN, load_template, load_template_text, split_subject, template_path,
)
from automation.tests.test_actions import make_context, make_deck


@pytest.fixture
def folders(tmp_path, monkeypatch):
    new, legacy = tmp_path / "text_templates", tmp_path / "email_templates"
    new.mkdir()
    legacy.mkdir()
    monkeypatch.setattr(text_templates, "TEMPLATES_DIR", new)
    monkeypatch.setattr(text_templates, "LEGACY_DIR", legacy)
    return new, legacy


@pytest.mark.parametrize("name", ["willkommen", "Ticket-Eingang", "mail 2", "Übersicht_1", "a", "x" * 60])
def test_valid_names(name):
    assert NAME_PATTERN.fullmatch(name)


@pytest.mark.parametrize("name", ["", " ", "../secret", "a/b", "a\\b", "a.b", "..", ".hidden", "x" * 61, "a\nb", "-start", "tab\t", " name", "name "])
def test_names_that_could_leave_the_folder_or_are_odd_are_refused(name, tmp_path):
    with pytest.raises(ValueError):
        template_path(tmp_path, name)


def test_split_subject():
    assert split_subject("Subject: Hallo\n\nText\nzwei") == ("Hallo", "Text\nzwei")
    assert split_subject("Nur Text") == (None, "Nur Text")
    assert split_subject("\nSubject: x\n\nText")[0] is None  # a leading blank line: no subject header


def test_one_template_serves_email_and_plain_text(folders):
    new, _ = folders
    (new / "gruss.txt").write_text("Subject: Hallo $name\n\nGuten Tag $name\n", encoding="utf-8")
    assert load_template("gruss") == ("Hallo $name", "Guten Tag $name\n")
    assert load_template_text("gruss") == "Guten Tag $name\n"  # the subject line is for e-mails only


def test_templates_not_moved_over_yet_are_still_found_in_the_old_folder(folders):
    new, legacy = folders
    (legacy / "alt.txt").write_text("Subject: Alt\n\nText", encoding="utf-8")
    assert load_template("alt") == ("Alt", "Text")
    (new / "alt.txt").write_text("Neu", encoding="utf-8")
    assert load_template("alt") == (None, "Neu")  # the new folder wins


def test_add_comment_uses_a_text_template_and_substitutes_variables(folders):
    new, _ = folders
    (new / "freigabe.txt").write_text("Freigabe für $name\n", encoding="utf-8")
    deck = make_deck()
    context = make_context(deck)
    context.variables["name"] = "Anna"
    out = AddCommentAction().execute(context, {"message": "ignoriert", "text_template": "freigabe"})
    assert out == {"message": "Freigabe für Anna\n"}
    assert deck.calls[-1] == ("add_comment", 100, "Freigabe für Anna\n")


def test_add_comment_without_a_template_is_unchanged():
    deck = make_deck()
    context = make_context(deck)
    context.variables["x"] = "1"
    for extra in ({}, {"text_template": None}, {"text_template": ""}):
        assert AddCommentAction().execute(context, {"message": "Wert $x", **extra}) == {"message": "Wert 1"}


def test_format_text_uses_a_text_template(folders):
    new, _ = folders
    (new / "kopf.txt").write_text("Ticket $nr: $titel", encoding="utf-8")
    out = FormatTextAction().execute(
        make_context(make_deck()), {"template": "ignoriert", "text_template": "kopf", "values": {"nr": 7, "titel": "Drucker"}}
    )
    assert out == {"text": "Ticket 7: Drucker"}


def test_the_same_template_works_in_format_text_and_in_an_email(folders, tmp_path, monkeypatch):
    new, _ = folders
    (new / "beides.txt").write_text("Subject: Betreff $x\n\nText $x", encoding="utf-8")
    assert FormatTextAction().execute(make_context(make_deck()), {"text_template": "beides", "values": {"x": 1}}) == {"text": "Text 1"}
    assert send_email_module._load_template("beides") == ("Betreff $x", "Text $x")


def test_an_unknown_template_fails_with_a_clear_message(folders):
    with pytest.raises(FileNotFoundError, match="Unknown template 'fehlt'"):
        AddCommentAction().execute(make_context(make_deck()), {"message": "", "text_template": "fehlt"})


def test_a_path_in_the_template_name_never_reaches_the_file_system(folders, tmp_path):
    (tmp_path / "geheim.txt").write_text("nicht lesen", encoding="utf-8")
    for call in (
        lambda: AddCommentAction().execute(make_context(make_deck()), {"message": "", "text_template": "../geheim"}),
        lambda: FormatTextAction().execute(make_context(make_deck()), {"template": "", "text_template": "../geheim", "values": {}}),
        lambda: send_email_module._load_template("../geheim"),
    ):
        with pytest.raises(ValueError):
            call()
