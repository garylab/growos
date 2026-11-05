"""Provider usage rollups and the per-project AI token budget guardrail."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Project, ProviderUsage


def month_start(today: date | None = None) -> datetime:
    t = today or date.today()
    return datetime(t.year, t.month, 1, tzinfo=UTC)


def monthly_tokens(db: Session, project_id: uuid.UUID) -> int:
    v = db.scalar(select(func.coalesce(func.sum(ProviderUsage.tokens_in + ProviderUsage.tokens_out), 0))
                  .where(ProviderUsage.project_id == project_id, ProviderUsage.created_at >= month_start()))
    return int(v or 0)


def token_budget(project: Project) -> int:
    """0 means unlimited. Per-project setting overrides the deployment default."""
    econ = (project.settings or {}).get("budget") or {}
    v = econ.get("monthly_token_budget")
    return int(v) if v is not None else get_settings().default_monthly_token_budget


class BudgetExceeded(RuntimeError):
    pass


def check_budget(db: Session, project: Project) -> None:
    """Raise BudgetExceeded when this month's AI token use is at or over the project budget."""
    budget = token_budget(project)
    if budget <= 0:
        return
    used = monthly_tokens(db, project.id)
    if used >= budget:
        raise BudgetExceeded(
            f"This project has used {used:,} of its {budget:,} monthly AI token budget. Raise it under Settings "
            "or wait for next month. (Set the budget to 0 for unlimited.)")


def usage_summary(db: Session, project_id: uuid.UUID, project: Project, months: int = 6) -> dict[str, Any]:
    by_provider = db.execute(
        select(ProviderUsage.provider_key, func.coalesce(func.sum(ProviderUsage.tokens_in + ProviderUsage.tokens_out), 0),
               func.coalesce(func.sum(ProviderUsage.units), 0), func.count())
        .where(ProviderUsage.project_id == project_id, ProviderUsage.created_at >= month_start())
        .group_by(ProviderUsage.provider_key)).all()
    monthly = db.execute(
        select(func.date_trunc("month", ProviderUsage.created_at).label("m"),
               func.coalesce(func.sum(ProviderUsage.tokens_in + ProviderUsage.tokens_out), 0))
        .where(ProviderUsage.project_id == project_id)
        .group_by("m").order_by("m")).all()
    by_op = db.execute(
        select(ProviderUsage.operation, func.coalesce(func.sum(ProviderUsage.tokens_in + ProviderUsage.tokens_out), 0))
        .where(ProviderUsage.project_id == project_id, ProviderUsage.created_at >= month_start())
        .group_by(ProviderUsage.operation).order_by(func.sum(ProviderUsage.tokens_in + ProviderUsage.tokens_out).desc())).all()
    budget = token_budget(project)
    used = monthly_tokens(db, project_id)
    return {
        "month": month_start().date().isoformat(),
        "tokens_this_month": used,
        "budget": budget,
        "budget_used_pct": round(used / budget, 3) if budget else None,
        "by_provider": [{"provider_key": p, "tokens": int(t), "units": float(u), "calls": int(c)} for p, t, u, c in by_provider],
        "by_operation": [{"operation": o, "tokens": int(t)} for o, t in by_op][:15],
        "monthly_tokens": [{"month": m.date().isoformat(), "tokens": int(t)} for m, t in monthly[-months:]],
    }


