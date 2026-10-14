from __future__ import annotations

from automation.actions_registry.format_text import FormatTextAction
from automation.core.domain.models import DeckEvent, EventType
from automation.core.ports.action_module import ActionContext
from automation.testing.fakes import InMemoryActionRegistry, InMemoryDeckGateway


def make_context() -> ActionContext:
    return ActionContext(
        event=DeckEvent(instance="test", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10),
        deck=InMemoryDeckGateway(),
        modules=InMemoryActionRegistry({}),
    )


def test_substitutes_values_into_the_template():
    output = FormatTextAction().execute(
        make_context(), {"template": "Ticket-Nr: $number ($title)", "values": {"number": "0042", "title": "Server down"}}
    )

    assert output == {"text": "Ticket-Nr: 0042 (Server down)"}


def test_non_string_values_are_stringified():
    output = FormatTextAction().execute(make_context(), {"template": "Count: $n", "values": {"n": 5}})

    assert output == {"text": "Count: 5"}


def test_unresolved_placeholder_is_left_as_is():
    output = FormatTextAction().execute(make_context(), {"template": "Hello $missing", "values": {}})

    assert output == {"text": "Hello $missing"}


def test_declares_its_input_and_output_shape():
    action = FormatTextAction()

    assert action.default_input() == {"template": "", "values": {}}
    assert action.default_output() == {"text": ""}
