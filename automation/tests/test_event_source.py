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


def test_due_date_change_is_detected_alongside_card_updated():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1, "duedate": None}]}]})
    source = PollingEventSource(deck, InMemorySnapshotStore())
    source.poll("inst", 1)

    deck.stacks[1][0]["cards"][0]["duedate"] = "2026-01-05T10:00:00+00:00"
    deck.stacks[1][0]["cards"][0]["lastModified"] = 2

    events = source.poll("inst", 1)

    assert {e.event_type for e in events} == {EventType.CARD_DUE_DATE_CHANGED, EventType.CARD_UPDATED}


def test_description_change_is_detected():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1, "description": "old"}]}]})
    source = PollingEventSource(deck, InMemorySnapshotStore())
    source.poll("inst", 1)

    deck.stacks[1][0]["cards"][0]["description"] = "new"
    deck.stacks[1][0]["cards"][0]["lastModified"] = 2

    events = source.poll("inst", 1)

    assert EventType.CARD_DESCRIPTION_CHANGED in {e.event_type for e in events}


def test_new_assignee_is_detected():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1, "assignedUsers": []}]}]})
    source = PollingEventSource(deck, InMemorySnapshotStore())
    source.poll("inst", 1)

    deck.stacks[1][0]["cards"][0]["assignedUsers"] = [{"participant": {"uid": "alice"}}]
    deck.stacks[1][0]["cards"][0]["lastModified"] = 2

    events = source.poll("inst", 1)

    assert EventType.CARD_ASSIGNED in {e.event_type for e in events}


def test_unassigning_everyone_does_not_fire_card_assigned():
    deck = InMemoryDeckGateway(
        {1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1, "assignedUsers": [{"participant": {"uid": "alice"}}]}]}]}
    )
    source = PollingEventSource(deck, InMemorySnapshotStore())
    source.poll("inst", 1)

    deck.stacks[1][0]["cards"][0]["assignedUsers"] = []
    deck.stacks[1][0]["cards"][0]["lastModified"] = 2

    events = source.poll("inst", 1)

    assert EventType.CARD_ASSIGNED not in {e.event_type for e in events}
    assert EventType.CARD_UPDATED in {e.event_type for e in events}


def test_deleted_card_is_detected():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1}]}]})
    source = PollingEventSource(deck, InMemorySnapshotStore())
    source.poll("inst", 1)

    deck.stacks[1][0]["cards"] = []

    events = source.poll("inst", 1)

    assert len(events) == 1
    assert events[0].event_type == EventType.CARD_DELETED
    assert events[0].card_id == 100
