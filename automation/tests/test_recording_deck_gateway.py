from __future__ import annotations

from automation.adapters.recording_deck_gateway import RecordingDeckGateway
from automation.testing.fakes import InMemoryDeckGateway


def test_records_boards_written_to_but_not_reads_or_board_less_calls():
    written: set = set()
    deck = RecordingDeckGateway(
        InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 5, "lastModified": 1}]}], 2: [{"id": 20, "cards": []}]}),
        "prod", written,
    )

    deck.list_stacks(1)
    deck.list_cards(board_id=1, stack_id=10)
    deck.add_comment(card_id=5, message="x")
    assert written == set()

    deck.set_title(board_id=1, stack_id=10, card_id=5, title="t")
    deck.create_card(board_id=2, stack_id=20, title="copy")
    assert written == {("prod", 1), ("prod", 2)}
