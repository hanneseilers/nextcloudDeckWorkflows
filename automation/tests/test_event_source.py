from __future__ import annotations

from automation.adapters.nextcloud.event_source import PollingEventSource
from automation.core.domain.models import EventType
from automation.testing.fakes import InMemoryDeckGateway, InMemorySnapshotStore


def test_new_card_is_detected_as_created():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1}]}]})
    source = PollingEventSource(deck, InMemorySnapshotStore())

    events = source.poll("inst", 1)

    assert len(events) == 1
    assert events[0].event_type == EventType.CARD_CREATED
    assert events[0].card_id == 100
    assert events[0].stack_id == 10


def test_second_poll_without_changes_yields_no_events():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1}]}]})
    snapshots = InMemorySnapshotStore()
    source = PollingEventSource(deck, snapshots)
    source.poll("inst", 1)

    assert source.poll("inst", 1) == []


def test_moved_card_is_detected():
    deck = InMemoryDeckGateway(
        {1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1}]}, {"id": 20, "cards": []}]}
    )
    source = PollingEventSource(deck, InMemorySnapshotStore())
    source.poll("inst", 1)

    deck.stacks[1][0]["cards"] = []
    deck.stacks[1][1]["cards"] = [{"id": 100, "lastModified": 1}]

    events = source.poll("inst", 1)

    assert len(events) == 1
    assert events[0].event_type == EventType.CARD_MOVED
    assert events[0].stack_id == 20
    assert events[0].previous_stack_id == 10


def test_updated_card_is_detected():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1}]}]})
    source = PollingEventSource(deck, InMemorySnapshotStore())
    source.poll("inst", 1)

    deck.stacks[1][0]["cards"][0]["lastModified"] = 2

    events = source.poll("inst", 1)

    assert len(events) == 1
    assert events[0].event_type == EventType.CARD_UPDATED


def test_deleted_card_is_detected():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1}]}]})
    source = PollingEventSource(deck, InMemorySnapshotStore())
    source.poll("inst", 1)

    deck.stacks[1][0]["cards"] = []

    events = source.poll("inst", 1)

    assert len(events) == 1
    assert events[0].event_type == EventType.CARD_DELETED
    assert events[0].card_id == 100
