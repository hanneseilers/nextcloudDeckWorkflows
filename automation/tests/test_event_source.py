from __future__ import annotations

from automation.adapters.nextcloud.event_source import PollingEventSource
from automation.core.domain.models import EventType
from automation.testing.fakes import InMemoryDeckGateway, InMemorySnapshotStore


def poll_and_commit(source: PollingEventSource, instance: str, board_id: int):
    """poll() alone no longer persists the new snapshot (see
    PollingEventSource's docstring - commit() must follow once the caller is
    done with the events, so a crash in between doesn't lose them). Tests
    that don't care about that distinction just want both steps done."""

    events = source.poll(instance, board_id)
    source.commit(instance, board_id)
    return events


def test_new_card_is_detected_as_created():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1}]}]})
    source = PollingEventSource(deck, InMemorySnapshotStore())

    events = poll_and_commit(source, "inst", 1)

    assert len(events) == 1
    assert events[0].event_type == EventType.CARD_CREATED
    assert events[0].card_id == 100
    assert events[0].stack_id == 10


def test_second_poll_without_changes_yields_no_events():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1}]}]})
    snapshots = InMemorySnapshotStore()
    source = PollingEventSource(deck, snapshots)
    poll_and_commit(source, "inst", 1)

    assert poll_and_commit(source, "inst", 1) == []


def test_poll_without_commit_does_not_persist_the_snapshot():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1}]}]})
    source = PollingEventSource(deck, InMemorySnapshotStore())

    first = source.poll("inst", 1)  # no commit()
    second = source.poll("inst", 1)  # must detect the exact same card as new again

    assert [e.event_type for e in first] == [EventType.CARD_CREATED]
    assert [e.event_type for e in second] == [EventType.CARD_CREATED]


def test_commit_after_a_fresh_poll_replaces_the_pending_snapshot():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1}]}]})
    source = PollingEventSource(deck, InMemorySnapshotStore())

    source.poll("inst", 1)  # pending: card 100 at last_modified=1
    deck.stacks[1][0]["cards"][0]["lastModified"] = 2
    source.poll("inst", 1)  # pending now overwritten: last_modified=2
    source.commit("inst", 1)

    assert poll_and_commit(source, "inst", 1) == []  # nothing changed since the committed state


def test_moved_card_is_detected():
    deck = InMemoryDeckGateway(
        {1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1}]}, {"id": 20, "cards": []}]}
    )
    source = PollingEventSource(deck, InMemorySnapshotStore())
    poll_and_commit(source, "inst", 1)

    deck.stacks[1][0]["cards"] = []
    deck.stacks[1][1]["cards"] = [{"id": 100, "lastModified": 1}]

    events = poll_and_commit(source, "inst", 1)

    assert len(events) == 1
    assert events[0].event_type == EventType.CARD_MOVED
    assert events[0].stack_id == 20
    assert events[0].previous_stack_id == 10


def test_updated_card_is_detected():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1}]}]})
    source = PollingEventSource(deck, InMemorySnapshotStore())
    poll_and_commit(source, "inst", 1)

    deck.stacks[1][0]["cards"][0]["lastModified"] = 2

    events = poll_and_commit(source, "inst", 1)

    assert len(events) == 1
    assert events[0].event_type == EventType.CARD_UPDATED


def test_due_date_change_is_detected_alongside_card_updated():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1, "duedate": None}]}]})
    source = PollingEventSource(deck, InMemorySnapshotStore())
    poll_and_commit(source, "inst", 1)

    deck.stacks[1][0]["cards"][0]["duedate"] = "2026-01-05T10:00:00+00:00"
    deck.stacks[1][0]["cards"][0]["lastModified"] = 2

    events = poll_and_commit(source, "inst", 1)

    assert {e.event_type for e in events} == {EventType.CARD_DUE_DATE_CHANGED, EventType.CARD_UPDATED}


def test_description_change_is_detected():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1, "description": "old"}]}]})
    source = PollingEventSource(deck, InMemorySnapshotStore())
    poll_and_commit(source, "inst", 1)

    deck.stacks[1][0]["cards"][0]["description"] = "new"
    deck.stacks[1][0]["cards"][0]["lastModified"] = 2

    events = poll_and_commit(source, "inst", 1)

    assert EventType.CARD_DESCRIPTION_CHANGED in {e.event_type for e in events}


def test_new_assignee_is_detected():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1, "assignedUsers": []}]}]})
    source = PollingEventSource(deck, InMemorySnapshotStore())
    poll_and_commit(source, "inst", 1)

    deck.stacks[1][0]["cards"][0]["assignedUsers"] = [{"participant": {"uid": "alice"}}]
    deck.stacks[1][0]["cards"][0]["lastModified"] = 2

    events = poll_and_commit(source, "inst", 1)

    assert EventType.CARD_ASSIGNED in {e.event_type for e in events}


def test_unassigning_everyone_does_not_fire_card_assigned():
    deck = InMemoryDeckGateway(
        {1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1, "assignedUsers": [{"participant": {"uid": "alice"}}]}]}]}
    )
    source = PollingEventSource(deck, InMemorySnapshotStore())
    poll_and_commit(source, "inst", 1)

    deck.stacks[1][0]["cards"][0]["assignedUsers"] = []
    deck.stacks[1][0]["cards"][0]["lastModified"] = 2

    events = poll_and_commit(source, "inst", 1)

    assert EventType.CARD_ASSIGNED not in {e.event_type for e in events}
    assert EventType.CARD_UPDATED in {e.event_type for e in events}


def test_deleted_card_is_detected():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1}]}]})
    source = PollingEventSource(deck, InMemorySnapshotStore())
    poll_and_commit(source, "inst", 1)

    deck.stacks[1][0]["cards"] = []

    events = poll_and_commit(source, "inst", 1)

    assert len(events) == 1
    assert events[0].event_type == EventType.CARD_DELETED
    assert events[0].card_id == 100
