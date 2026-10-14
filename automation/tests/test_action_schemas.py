from __future__ import annotations

from automation import actions_registry
from automation.actions_registry.calendar_lookup import CalendarLookupAction
from automation.actions_registry.send_email import SendEmailAction
from automation.actions_registry.set_title import SetTitleAction
from automation.adapters.actions.base import WorkflowAction
from automation.adapters.actions.loader import ModuleLoader


def test_base_class_defaults_to_empty_json_objects():
    class BareAction(WorkflowAction):
        ACTION_NAME = "bare"

        def execute(self, context, params):
            return {}

    action = BareAction()

    assert action.default_input() == {}
    assert action.default_output() == {}


def test_every_registered_action_declares_json_object_shaped_defaults():
    loader = ModuleLoader(actions_registry)

    for name in loader.list_names():
        action = loader.get(name)
        assert isinstance(action.default_input(), dict), name
        assert isinstance(action.default_output(), dict), name


def test_set_title_declares_its_input_shape():
    assert SetTitleAction().default_input() == {"title": ""}


def test_calendar_lookup_declares_its_input_and_output_shapes():
    action = CalendarLookupAction()

    assert action.default_input() == {"calendar_id": "", "title_contains": ""}
    assert action.default_output() == {"title": None, "start": None, "end": None, "location": None}


def test_send_email_declares_its_input_shape():
    assert SendEmailAction().default_input() == {
        "to": "", "subject": "", "body": "", "template": None, "template_data": {},
    }
