from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_editable_project, get_project
from app.core.db import get_db
from app.intelligence.scorecard import DEFAULT_ECONOMICS, build_scorecard
from app.models import Project

router = APIRouter(prefix="/projects/{project_id}/scorecard", tags=["scorecard"])


class EconomicsIn(BaseModel):
    """Inputs the money model needs. Without an average order value no monetary figure is produced."""
    currency: str = "USD"
    average_order_value: float | None = Field(default=None, ge=0)
    assumed_conversion_rate: float | None = Field(default=None, ge=0, le=1)
    revenue_multiple_low: float | None = Field(default=None, ge=0, le=50)
    revenue_multiple_high: float | None = Field(default=None, ge=0, le=50)
    gross_margin: float | None = Field(default=None, ge=0, le=1)


@router.get("")
def scorecard(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> dict[str, Any]:
    return build_scorecard(db, project)


@router.put("/economics")
def set_economics(body: EconomicsIn, project: Project = Depends(get_editable_project), db: Session = Depends(get_db)):
    econ = {**DEFAULT_ECONOMICS, **((project.settings or {}).get("economics") or {}),
            **{k: v for k, v in body.model_dump().items() if v is not None}}
    project.settings = {**(project.settings or {}), "economics": econ}
    db.commit()
    return econ
