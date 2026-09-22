from __future__ import annotations

import importlib

from automation import actions_registry
from automation.adapters.actions.loader import ModuleLoader, _drop_modules_with_unmet_requirements
from automation.core.domain.models import DeckEvent, EventType
from automation.core.ports.action_module import ActionContext, UnknownActionError
from automation.testing.fakes import InMemoryDeckGateway


class FakeAction:
    """Minimal stand-in for a WorkflowAction, used to test the pure dependency
    resolution logic without needing real files on disk."""

    def __init__(self, name: str, requires: tuple[str, ...] = ()) -> None:
        self.ACTION_NAME = name
        self.REQUIRES = requires

    def execute(self, context, params):
        return None


def test_modules_with_unmet_dependencies_are_dropped():
    actions = {
        "a": FakeAction("a"),
        "b": FakeAction("b", requires=("a",)),
        "c": FakeAction("c", requires=("missing",)),
    }

    result = _drop_modules_with_unmet_requirements(actions)

    assert set(result) == {"a", "b"}


def test_dependency_drops_cascade_through_a_chain():
    actions = {
        "a": FakeAction("a", requires=("missing",)),
        "b": FakeAction("b", requires=("a",)),
        "c": FakeAction("c", requires=("b",)),
    }

    result = _drop_modules_with_unmet_requirements(actions)

    assert result == {}


def test_discover_skips_a_broken_module_and_keeps_the_rest(tmp_path, monkeypatch):
    pkg_dir = tmp_path / "broken_actions_pkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "good.py").write_text(
        "from automation.adapters.actions.base import WorkflowAction\n"
        "class GoodAction(WorkflowAction):\n"
        "    ACTION_NAME = 'good'\n"
        "    def execute(self, context, params):\n"
        "        return 'ok'\n"
    )
    (pkg_dir / "broken.py").write_text("raise RuntimeError('boom at import time')\n")

    monkeypatch.syspath_prepend(str(tmp_path))
    package = importlib.import_module("broken_actions_pkg")

    loader = ModuleLoader(package)

    assert loader.list_names() == ["good"]
    assert loader.get("good").execute(None, {}) == "ok"


def test_unknown_action_raises_a_catchable_error():
    loader = ModuleLoader(actions_registry)

    try:
        loader.get("this_action_does_not_exist")
        assert False, "expected UnknownActionError"
    except UnknownActionError:
        pass


def test_real_registry_includes_the_standard_actions():
    names = set(ModuleLoader(actions_registry).list_names())

    assert {
        "log_action", "set_title", "set_description", "set_due_date", "move_card",
        "add_label", "assign_user", "unassign_user", "add_comment",
        "calendar_lookup", "send_email",
    } <= names


class AppointmentSummaryAction:
    """Test-only example of a module calling another module via context.modules -
    the mechanism the calendar_lookup/send_email pairing will use later."""

    ACTION_NAME = "appointment_summary"
    REQUIRES = ("calendar_lookup",)

    def execute(self, context: ActionContext, params: dict) -> str:
        appointment = context.modules.get("calendar_lookup").execute(context, params["appointment"])
        return f"{appointment['summary']} at {appointment['start']}"


def test_one_module_can_call_another_module_and_use_its_return_value():
    loader = ModuleLoader(actions_registry)
    calendar = loader.get("calendar_lookup")
    consumer = AppointmentSummaryAction()

    context = ActionContext(
        event=DeckEvent(instance="test", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10),
        deck=InMemoryDeckGateway(),
        modules=loader,
    )

    summary = consumer.execute(context, {"appointment": {"summary": "Sync", "start": "2026-01-05T10:00"}})

    assert summary == "Sync at 2026-01-05T10:00"
    # sanity check that context.modules really is the same registry calendar came from
    assert context.modules.get("calendar_lookup") is calendar
