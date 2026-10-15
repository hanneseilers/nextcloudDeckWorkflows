from __future__ import annotations

import random
import time
from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class GenerateRandomNumberAction(WorkflowAction):
    """Generates a random number (digits only, leading zeros allowed) that
    hasn't been generated before in the same named list - e.g. for a unique
    ticket/ID number. Keeps retrying with an increasing digit count if the
    current width runs out of unused numbers, so it (almost) always
    eventually succeeds rather than looping forever: after 5 consecutive
    collisions at the current width, the width grows by 1 and the
    collision count resets, repeating until a free number is found.

    params:
      list_name: str - which pool of previously-generated numbers to check
        against/add to; independent workflows can use different lists so
        they don't collide with each other (default "default")
      min_digits: int - starting/minimum number of digits; numbers are
        zero-padded to the current width, e.g. min_digits=4 might generate
        "0042" (default 4)
      save: bool - whether to record the generated number in the list, so
        it won't be generated again until forget_random_number removes it
        - this is the point of the feature, so it defaults to true
        (default true)

    output:
      number: str - the generated number, zero-padded to its final width
    """

    ACTION_NAME: ClassVar[str] = "generate_random_number"

    # After this many consecutive collisions at the current digit width,
    # widen by one digit and start a fresh attempt round.
    _MAX_CONSECUTIVE_MISSES = 5
    # Purely a defensive backstop against a genuine infinite loop (e.g. a
    # bug that makes every candidate look "already used") - far beyond any
    # digit count a real workflow would ever need.
    _MAX_DIGITS = 30

    def default_input(self) -> dict[str, Any]:
        return {"list_name": "default", "min_digits": 4, "save": True}

    def default_output(self) -> dict[str, Any]:
        return {"number": ""}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        if context.sequence_store is None:
            raise RuntimeError("generate_random_number: no sequence store available for this run")

        list_name = str(params.get("list_name") or "default")
        # `or 4` would also treat an explicit min_digits=0 as "not given" and
        # silently promote it to 4 - check for None (missing/null) instead so
        # 0 (clamped to 1 by max() below) is respected as the caller intended.
        raw_min_digits = params.get("min_digits")
        digits = max(1, int(raw_min_digits if raw_min_digits is not None else 4))
        save = params.get("save", True)
        # A local Random instance (not the global `random` module) seeded
        # from the current timestamp - doesn't disturb any other code that
        # uses `random` globally.
        rng = random.Random(time.time_ns())

        misses = 0
        while True:
            if digits > self._MAX_DIGITS:
                raise RuntimeError(
                    f"generate_random_number: no unused number found in list '{list_name}' "
                    f"even at {self._MAX_DIGITS} digits"
                )
            candidate = f"{rng.randrange(10 ** digits):0{digits}d}"
            if not context.sequence_store.contains_number(list_name, candidate):
                if save:
                    context.sequence_store.add_number(list_name, candidate)
                return {"number": candidate}

            misses += 1
            if misses >= self._MAX_CONSECUTIVE_MISSES:
                digits += 1
                misses = 0
