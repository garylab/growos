from app.queue.base import TaskQueue
from app.queue.postgres import PostgresTaskQueue

__all__ = ["TaskQueue", "PostgresTaskQueue", "get_queue"]


def get_queue() -> TaskQueue:
    return PostgresTaskQueue()
