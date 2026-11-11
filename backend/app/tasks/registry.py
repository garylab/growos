"""Task registry: task_type -> handler(ctx) -> result dict."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.tasks.context import TaskContext

TaskHandler = Callable[[TaskContext], dict[str, Any]]
_REGISTRY: dict[str, TaskHandler] = {}
TASK_DESCRIPTIONS: dict[str, str] = {}

# Which worker runs a task. Nearly everything is pure Python and runs on the default worker; a task naming another
# queue needs something that worker's image does not carry — crawling needs the SiteOne binary, which in turn needs
# a newer glibc than the rest of the stack wants to be pinned to.
#
# Declared beside the handler rather than listed in an environment variable per deployment, so adding a
# crawler-only task cannot drift out of sync with the compose file.
DEFAULT_QUEUE = "default"
TASK_QUEUES: dict[str, str] = {}


def task(task_type: str, description: str = "", queue: str = DEFAULT_QUEUE) -> Callable[[TaskHandler], TaskHandler]:
    def deco(fn: TaskHandler) -> TaskHandler:
        _REGISTRY[task_type] = fn
        TASK_DESCRIPTIONS[task_type] = description
        TASK_QUEUES[task_type] = queue
        return fn
    return deco


def task_types_for_queue(queue: str) -> list[str]:
    """Task types a worker on this queue may claim. Call after `load_all()`."""
    return sorted(t for t, q in TASK_QUEUES.items() if q == queue)


def get_task(task_type: str) -> TaskHandler:
    if task_type not in _REGISTRY:
        raise KeyError(f"Unknown task type '{task_type}'")
    return _REGISTRY[task_type]


def all_tasks() -> dict[str, str]:
    return dict(TASK_DESCRIPTIONS)


def load_all() -> None:
    """Import task modules so their decorators register handlers."""
    import app.tasks.backlinks  # noqa: F401
    import app.tasks.bing  # noqa: F401
    import app.tasks.search_data  # noqa: F401
    import app.tasks.brand  # noqa: F401
    import app.tasks.competitor  # noqa: F401
    import app.tasks.crawl  # noqa: F401
    import app.tasks.geo  # noqa: F401
    import app.tasks.gsc  # noqa: F401
    import app.tasks.performance  # noqa: F401
    import app.tasks.ai_analysis  # noqa: F401
    import app.tasks.analytics  # noqa: F401
    import app.tasks.plan  # noqa: F401
    import app.tasks.content  # noqa: F401
    import app.tasks.scorecard_task  # noqa: F401
    import app.tasks.outcomes  # noqa: F401
