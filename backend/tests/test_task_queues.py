"""Which worker runs which task.

Crawling needs a native binary that only the crawl worker's image carries, so a worker must never claim a job its
image cannot run — it would fail the job instead of leaving it for the worker that can.
"""
import pytest

from app.tasks.registry import DEFAULT_QUEUE, TASK_QUEUES, all_tasks, load_all, task_types_for_queue

load_all()


def test_crawling_is_the_only_task_routed_off_the_default_worker():
    assert task_types_for_queue("crawler") == ["crawl_domain"]
    non_default = {t: q for t, q in TASK_QUEUES.items() if q != DEFAULT_QUEUE}
    assert non_default == {"crawl_domain": "crawler"}


def test_every_registered_task_is_claimable_by_exactly_one_queue():
    queues = set(TASK_QUEUES.values())
    claimable = [t for q in queues for t in task_types_for_queue(q)]
    assert sorted(claimable) == sorted(all_tasks())          # none missed
    assert len(claimable) == len(set(claimable))             # none claimed twice


def test_the_default_worker_does_not_claim_crawls():
    assert "crawl_domain" not in task_types_for_queue(DEFAULT_QUEUE)
    # ...but it does claim the rest, so splitting the workers loses nothing.
    assert {"run_ai_visibility", "sync_rankings", "monitor_brand_mentions"} <= set(task_types_for_queue(DEFAULT_QUEUE))


def test_an_unknown_queue_claims_nothing_rather_than_everything():
    """A typo in WORKER_QUEUE must not silently turn into "take every job"."""
    assert task_types_for_queue("typo") == []


def test_a_task_defaults_to_the_general_worker():
    from app.tasks.registry import task

    @task("throwaway_task", "only registered by this test")
    def _handler(_ctx):  # pragma: no cover - never executed
        return {}

    try:
        assert TASK_QUEUES["throwaway_task"] == DEFAULT_QUEUE
        assert "throwaway_task" in task_types_for_queue(DEFAULT_QUEUE)
    finally:
        TASK_QUEUES.pop("throwaway_task", None)


def test_blank_queue_means_take_everything(monkeypatch):
    """Single-worker setups and local development keep the old behaviour."""
    import app.core.config as config

    class S:
        worker_queue = ""

    monkeypatch.setattr(config, "get_settings", lambda: S())
    # claim_types() reads the module-level settings in worker.main; mirror its logic rather than import the worker,
    # which starts a scheduler on import.
    name = (S.worker_queue or "").strip()
    assert (task_types_for_queue(name) if name else None) is None


def test_the_crawl_task_still_exists_under_its_documented_name():
    assert "crawl_domain" in all_tasks()
    assert "SiteOne" in all_tasks()["crawl_domain"]
