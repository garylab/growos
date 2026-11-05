import uuid
from types import SimpleNamespace

import pytest

from app.services.usage import BudgetExceeded, check_budget, token_budget


class FakeScalar:
    def __init__(self, value): self._v = value
    def scalar(self, *_a, **_k): return self._v


def project_with_budget(n):
    return SimpleNamespace(id=uuid.uuid4(), settings={"budget": {"monthly_token_budget": n}})


def test_token_budget_reads_project_setting():
    assert token_budget(project_with_budget(50000)) == 50000
    assert token_budget(SimpleNamespace(id=uuid.uuid4(), settings={})) == 0  # default deployment budget is 0


def test_check_budget_unlimited_never_raises():
    check_budget(FakeScalar(10**9), project_with_budget(0))  # 0 = unlimited, must not raise


def test_check_budget_raises_when_over(monkeypatch):
    import app.services.usage as u
    monkeypatch.setattr(u, "monthly_tokens", lambda db, pid: 60000)
    with pytest.raises(BudgetExceeded):
        check_budget(object(), project_with_budget(50000))


def test_check_budget_passes_when_under(monkeypatch):
    import app.services.usage as u
    monkeypatch.setattr(u, "monthly_tokens", lambda db, pid: 1000)
    check_budget(object(), project_with_budget(50000))  # under budget, no raise
