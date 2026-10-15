from __future__ import annotations

import pytest

from automation.core.domain.engine import _evaluate_condition
from automation.core.domain.models import ComparisonOp


@pytest.mark.parametrize(
    "op,left,right,expected",
    [
        (ComparisonOp.EQ, 5, 5, True),
        (ComparisonOp.EQ, 5, 6, False),
        (ComparisonOp.EQ, "5", 5, True),  # numeric coercion: string "5" == int 5
        (ComparisonOp.EQ, "high", "high", True),
        (ComparisonOp.EQ, "high", "low", False),
        (ComparisonOp.EQ, True, 1, True),  # Python's own bool-is-an-int equality, not our coercion
        (ComparisonOp.NE, 5, 6, True),
        (ComparisonOp.NE, 5, 5, False),
        (ComparisonOp.LT, 3, 5, True),
        (ComparisonOp.LT, "3", "5", True),  # numeric coercion
        (ComparisonOp.LT, "banana", "apple", False),  # non-numeric: string order
        (ComparisonOp.GT, 5, 3, True),
        (ComparisonOp.GT, 3, 5, False),
        (ComparisonOp.CONTAINS, "hello world", "wor", True),
        (ComparisonOp.CONTAINS, "hello world", "xyz", False),
        (ComparisonOp.BEGINS_WITH, "hello world", "hello", True),
        (ComparisonOp.BEGINS_WITH, "hello world", "world", False),
        (ComparisonOp.ENDS_WITH, "hello world", "world", True),
        (ComparisonOp.ENDS_WITH, "hello world", "hello", False),
    ],
)
def test_evaluate_condition(op, left, right, expected):
    assert _evaluate_condition(op, left, right) is expected


def test_none_is_compared_directly_without_crashing():
    assert _evaluate_condition(ComparisonOp.EQ, None, None) is True
    assert _evaluate_condition(ComparisonOp.NE, None, "x") is True


def test_unknown_operator_raises():
    with pytest.raises(ValueError):
        _evaluate_condition("not-a-real-op", 1, 1)
