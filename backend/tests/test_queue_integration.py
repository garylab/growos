"""Integration test for the PostgreSQL task queue. Runs only when RUN_DB_TESTS=1 and DATABASE_URL points to a test DB."""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RUN_DB_TESTS") != "1", reason="set RUN_DB_TESTS=1 with a test database")


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models import Base
    engine = create_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.rollback()
    s.close()


def test_enqueue_claim_complete_idempotent(db):
    from app.queue.postgres import PostgresTaskQueue
    q = PostgresTaskQueue()
    key = f"test:{uuid.uuid4()}"
    j1 = q.enqueue(db, task_type="build_growth_plan", params={}, project_id=None, idempotency_key=key)
    j2 = q.enqueue(db, task_type="build_growth_plan", params={}, project_id=None, idempotency_key=key)
    assert j1.id == j2.id
    db.commit()
    claimed = q.claim(db, "w1", ["build_growth_plan"])
    assert claimed is not None and claimed.status == "running" and claimed.attempts == 1
    assert q.heartbeat(db, claimed.id, 50, "half") is True
    q.complete(db, claimed.id, {"ok": True})
    db.refresh(claimed)
    assert claimed.status == "succeeded" and claimed.progress == 100
    j3 = q.enqueue(db, task_type="build_growth_plan", params={}, project_id=None, idempotency_key=key)
    assert j3.id != j1.id  # terminal job released the key
    db.commit()


def test_fail_retry_cancel(db):
    from app.queue.postgres import PostgresTaskQueue
    q = PostgresTaskQueue()
    j = q.enqueue(db, task_type="build_growth_plan", params={}, project_id=None, max_attempts=2)
    db.commit()
    c = q.claim(db, "w1")
    q.fail(db, c.id, "boom")
    db.refresh(c)
    assert c.status == "queued" and c.attempts == 1
    assert q.cancel(db, c.id) is True
    db.refresh(c)
    assert c.status == "cancelled"
    assert q.retry(db, c.id) is True
    db.refresh(c)
    assert c.status == "queued" and c.attempts == 0
