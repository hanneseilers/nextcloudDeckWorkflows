from __future__ import annotations

import pytest

from automation.actions_registry.calculate import CalculateAction
from automation.core.domain.models import DeckEvent, EventType
from automation.core.ports.action_module import ActionContext
from automation.testing.fakes import InMemoryActionRegistry, InMemoryDeckGateway


def make_context() -> ActionContext:
    return ActionContext(
        event=DeckEvent(instance="test", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10),
        deck=InMemoryDeckGateway(),
        modules=InMemoryActionRegistry({}),
    )


@pytest.mark.parametrize("op,left,right,expected", [
    ("add", 2, 3, 5),
    ("subtract", 5, 3, 2),
    ("multiply", 4, 3, 12),
    ("divide", 9, 3, 3),
])
def test_basic_operations(op, left, right, expected):
    output = CalculateAction().execute(make_context(), {"left": left, "right": right, "op": op})

    assert output == {"result": expected}
    assert isinstance(output["result"], int)  # whole results come back as int, not 4.0


def test_division_with_a_fractional_result_stays_a_float():
    output = CalculateAction().execute(make_context(), {"left": 7, "right": 2, "op": "divide"})

    assert output == {"result": 3.5}


def test_defaults_to_add_when_op_is_omitted():
    output = CalculateAction().execute(make_context(), {"left": 1, "right": 1})

    assert output == {"result": 2}


def test_unknown_op_raises_a_clear_error():
    with pytest.raises(ValueError, match="unknown op"):
        CalculateAction().execute(make_context(), {"left": 1, "right": 1, "op": "frobnicate"})


def test_division_by_zero_raises():
    with pytest.raises(ZeroDivisionError):
        CalculateAction().execute(make_context(), {"left": 1, "right": 0, "op": "divide"})


def test_declares_its_input_and_output_shape():
    action = CalculateAction()

    assert action.default_input() == {"left": 0, "right": 0, "op": "add"}
    assert action.default_output() == {"result": 0}
