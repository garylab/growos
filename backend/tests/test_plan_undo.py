"""Undo must restore exactly the state the previous completion left behind."""
from datetime import UTC, datetime, timedelta

from app.intelligence.playbook import CADENCE_DAYS, mark_complete, undo_complete
from app.models import PlanItem


def item(cadence="once", **kw):
    return PlanItem(cadence=cadence, status="todo", completions=[], **kw)


def test_undo_a_one_time_item():
    i = item()
    mark_complete(i, "done it")
    assert i.status == "done" and len(i.completions) == 1
    assert undo_complete(i) is True
    assert i.status == "todo" and i.completions == [] and i.last_done_at is None


def test_undo_an_item_marked_done_without_a_completion():
    i = item()
    i.status = "done"                     # what POST /status {done} does
    assert undo_complete(i) is True
    assert i.status == "todo" and i.last_done_at is None


def test_nothing_to_undo():
    assert undo_complete(item()) is False


def test_undo_a_routine_restores_the_earlier_due_date():
    cadence = next(iter(CADENCE_DAYS))
    i = item(cadence=cadence)
    mark_complete(i, "first")
    first_done, first_due = i.last_done_at, i.next_due_at
    mark_complete(i, "second")
    assert len(i.completions) == 2 and i.next_due_at != first_due

    assert undo_complete(i) is True
    assert len(i.completions) == 1
    assert i.completions[0]["note"] == "first"
    assert i.last_done_at == first_done
    assert i.next_due_at == first_due     # due date rolled back with it
    assert i.status == "todo"


def test_undoing_every_routine_completion_makes_it_due_now():
    cadence = next(iter(CADENCE_DAYS))
    i = item(cadence=cadence)
    mark_complete(i)
    assert undo_complete(i) is True
    assert i.completions == [] and i.last_done_at is None and i.next_due_at is None


def test_undo_keeps_timestamps_timezone_aware():
    i = item(cadence=next(iter(CADENCE_DAYS)))
    mark_complete(i)
    mark_complete(i)
    undo_complete(i)
    assert i.last_done_at.tzinfo is not None
    assert abs(i.last_done_at - datetime.now(UTC)) < timedelta(minutes=5)
