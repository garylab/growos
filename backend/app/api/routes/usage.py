from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_editable_project, get_project
from app.core.db import get_db
from app.models import Project
from app.services.usage import usage_summary

router = APIRouter(prefix="/projects/{project_id}/usage", tags=["usage"])


class BudgetIn(BaseModel):
    monthly_token_budget: int = Field(ge=0, description="0 = unlimited")


@router.get("")
def get_usage(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return usage_summary(db, project.id, project)


@router.put("/budget")
def set_budget(body: BudgetIn, project: Project = Depends(get_editable_project), db: Session = Depends(get_db)):
    project.settings = {**(project.settings or {}), "budget": {"monthly_token_budget": body.monthly_token_budget}}
    db.commit()
    return {"monthly_token_budget": body.monthly_token_budget}
