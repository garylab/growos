"""Controlled tools exposed to the AI analyst.

Each tool reads normalized data (never raw payloads) or performs a validated write. The analyst writes into the same
Growth Plan the user works from — there is no parallel list — and `add_plan_item` rejects any evidence whose record
ids do not exist in the database."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.intelligence import data as D
from app.intelligence.playbook import Draft, sync_one
from app.models import (ActionRecord, AIAnswerObservation, AnalyticsEvent, AuditFinding, BrandMention,
                        CompetitorObservation, Keyword, PerformanceObservation, PlanItem, Project, SearchObservation)

EVIDENCE_TABLES = {
    "audit_findings": AuditFinding, "search_observations": SearchObservation, "ai_answer_observations": AIAnswerObservation,
    "brand_mentions": BrandMention, "competitor_observations": CompetitorObservation, "performance_observations": PerformanceObservation,
    "analytics_events": AnalyticsEvent, "keywords": Keyword,
}

TOOL_SPECS: list[dict[str, Any]] = [
    {"name": "get_seo_findings", "description": "Latest crawl summary and top technical SEO findings for the project's primary domains.",
     "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "default": 40}}}},
    {"name": "get_search_performance", "description": "First-party Search Console totals, top pages and top query×page rows (28 days).",
     "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "default": 40}}}},
    {"name": "get_ai_visibility", "description": "Latest AI-visibility run: per prompt×provider brand/competitor mention rates and cited domains.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "get_analytics", "description": ("First-party website analytics: sessions, key events (conversions) and revenue per landing page, "
                                               "plus traffic sent by AI assistants (ChatGPT, Perplexity, Gemini …)."),
     "parameters": {"type": "object", "properties": {"days": {"type": "integer", "default": 28}, "limit": {"type": "integer", "default": 25}}}},
    {"name": "get_brand_mentions", "description": "Recent brand/competitor mentions from monitored sources with sentiment and intent.",
     "parameters": {"type": "object", "properties": {"days": {"type": "integer", "default": 30}, "limit": {"type": "integer", "default": 40}}}},
    {"name": "get_competitor_changes", "description": "Recent detected changes on watched competitor pages.",
     "parameters": {"type": "object", "properties": {"days": {"type": "integer", "default": 30}}}},
    {"name": "get_plan", "description": "The checklist the user already works from, so you do not repeat what is on it.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "add_plan_item",
     "description": ("Add one item to the user's Growth Plan. Only call this with evidence record ids returned by the "
                     "get_* tools. Every item must explain why it exists, reference the supporting records, and give "
                     "steps the user can actually follow."),
     "parameters": {"type": "object", "required": ["title", "why", "evidence", "impact", "confidence", "effort", "steps"],
                    "properties": {
                        "title": {"type": "string"}, "description": {"type": "string"},
                        "why": {"type": "string", "description": "Why this opportunity exists, citing the evidence."},

                        "evidence": {"type": "array", "items": {"type": "object", "required": ["table", "record_ids", "summary"],
                                                                 "properties": {"table": {"type": "string", "enum": list(EVIDENCE_TABLES)},
                                                                                "record_ids": {"type": "array", "items": {"type": "string"}},
                                                                                "summary": {"type": "string"}}}},
                        "impact": {"type": "number", "description": "0-100 potential business impact"},
                        "confidence": {"type": "number", "description": "0-1, how sure the evidence makes you"},
                        "effort": {"type": "integer", "description": "1 trivial .. 5 major project"},
                        "steps": {"type": "array", "items": {"type": "string"},
                                  "description": "2-5 concrete steps, in the order the user should do them"},
                        "category": {"type": "string", "enum": ["website", "content", "video", "community", "backlinks",
                                                                 "conversion", "competitors", "ai_visibility", "brand", "business"]},
                        "target_urls": {"type": "array", "items": {"type": "string"}},
                        "target_keywords": {"type": "array", "items": {"type": "string"}}}}},
    {"name": "update_action_status", "description": "Update the status of an optimization action.",
     "parameters": {"type": "object", "required": ["action_id", "status"],
                    "properties": {"action_id": {"type": "string"}, "status": {"type": "string", "enum": ["planned", "in_progress", "done", "cancelled"]},
                                   "note": {"type": "string"}}}},
]


class ToolRunner:
    def __init__(self, db: Session, project: Project):
        self.db, self.project = db, project
        self.created: list[str] = []

    def run(self, name: str, args: dict[str, Any]) -> str:
        fn = getattr(self, f"tool_{name}", None)
        if fn is None:
            return json.dumps({"error": f"unknown tool {name}"})
        try:
            return json.dumps(fn(**args), default=str)[:60_000]
        except TypeError as exc:
            return json.dumps({"error": f"bad arguments: {exc}"})
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            return json.dumps({"error": str(exc)[:500]})

    # ---------------------------------------------------------------- read tools
    def tool_get_seo_findings(self, limit: int = 40) -> dict[str, Any]:
        out: dict[str, Any] = {"domains": []}
        for d in D.primary_domains(self.db, self.project.id):
            run = D.latest_crawl_run(self.db, d.id)
            if not run:
                out["domains"].append({"domain": d.hostname, "status": "no crawl yet"})
                continue
            findings = D.crawl_findings(self.db, run.id)[:limit]
            out["domains"].append({"domain": d.hostname, "crawl_run_id": str(run.id), "finished_at": run.finished_at,
                                   "total_urls": run.total_urls, "html_pages": run.html_pages,
                                   "quality_scores": {c["code"]: c["score"] for c in run.quality_scores.get("categories", [])} | {"overall": (run.quality_scores.get("overall") or {}).get("score")},
                                   "findings_count": run.findings_count,
                                   "findings": [{"id": str(f.id), "code": f.code, "severity": f.severity, "url": f.url, "message": f.message} for f in findings]})
        return out

    def tool_get_search_performance(self, limit: int = 40) -> dict[str, Any]:
        out: dict[str, Any] = {"domains": []}
        for d in D.primary_domains(self.db, self.project.id):
            if not D.gsc_available(self.db, d.id):
                out["domains"].append({"domain": d.hostname, "status": "Search Console not connected or not synced"})
                continue
            start, end = D.gsc_window(28)
            rows = D.gsc_query_page_rows(self.db, d.id, 28, 10, limit)
            out["domains"].append({"domain": d.hostname, "totals_28d": D.gsc_totals(self.db, d.id, start, end),
                                   "top_pages": D.gsc_top_pages(self.db, d.id, 28, 15),
                                   "query_page_rows": [{**r, "record_ids": r.pop("ids")} for r in rows]})
        return out

    def tool_get_ai_visibility(self) -> dict[str, Any]:
        runs = D.latest_runs(self.db, self.project.id, 2)
        if not runs:
            return {"status": "no AI visibility runs yet"}
        rows = D.visibility_by_prompt(self.db, self.project.id, runs[0])
        for r in rows:
            r["record_ids"] = r.pop("observation_ids")
        return {"summary": D.visibility_summary(self.db, self.project.id, runs[0]),
                "previous_summary": D.visibility_summary(self.db, self.project.id, runs[1]) if len(runs) > 1 else None,
                "by_prompt": rows,
                "methodology": "API sampling; rates = share of samples mentioning the entity; not a consumer-app ranking."}

    def tool_get_analytics(self, days: int = 28, limit: int = 25) -> dict[str, Any]:
        out: dict[str, Any] = {"domains": []}
        for d in D.primary_domains(self.db, self.project.id):
            rows = D.analytics_landing_pages(self.db, d.id, days)
            if not rows:
                out["domains"].append({"domain": d.hostname, "status": "analytics not connected or not synced"})
                continue
            from datetime import date, timedelta
            end = date.today()
            start, prev_start = end - timedelta(days=days), end - timedelta(days=days * 2)
            out["domains"].append({
                "domain": d.hostname, "window_days": days,
                "totals": D.analytics_totals(self.db, d.id, start, end),
                "previous": D.analytics_totals(self.db, d.id, prev_start, start),
                "landing_pages": [{**{k: v for k, v in r.items() if k != "ids"}, "record_ids": r["ids"]} for r in rows[:limit]],
                "ai_assistant_traffic": D.ai_referral_traffic(self.db, d.id, days),
            })
        return out

    def tool_get_brand_mentions(self, days: int = 30, limit: int = 40) -> dict[str, Any]:
        ms = D.recent_mentions(self.db, self.project.id, days, limit)
        return {"count": len(ms), "mentions": [{"id": str(m.id), "source": m.source_name, "url": m.source_url, "entity": m.entity_name,
                                                "entity_type": m.entity_type, "sentiment": m.sentiment, "intent": m.intent,
                                                "topics": m.topics, "title": m.title, "excerpt": (m.content_excerpt or "")[:300],
                                                "published_at": m.published_at} for m in ms]}

    def tool_get_competitor_changes(self, days: int = 30) -> dict[str, Any]:
        obs = D.recent_competitor_changes(self.db, self.project.id, days)
        return {"changes": [{"id": str(o.id), "url": o.url, "observed_at": o.observed_at, "change_ratio": o.change_ratio,
                             "prices_added": o.diff_summary.get("prices_added"), "added": o.diff_summary.get("added", [])[:10]} for o in obs]}

    def tool_get_plan(self) -> dict[str, Any]:
        items = self.db.scalars(select(PlanItem).where(PlanItem.project_id == self.project.id,
                                                       PlanItem.status != "skipped")
                                .order_by(PlanItem.priority.desc()).limit(150)).all()
        return {"items": [{"id": str(i.id), "section": i.section, "category": i.category, "title": i.title,
                           "status": i.status, "priority": i.priority, "origin": i.origin} for i in items]}

    # ---------------------------------------------------------------- write tools
    def tool_add_plan_item(self, title: str, why: str, evidence: list[dict[str, Any]], impact: float,
                           confidence: float, effort: int, steps: list[str] | None = None,
                           description: str | None = None, recommended_action: str | None = None,
                           category: str = "content", target_urls: list[str] | None = None,
                           target_keywords: list[str] | None = None, **_ignored: Any) -> dict[str, Any]:
        """Extra keys the model invents are ignored rather than failing the call."""
        steps = [s for s in (steps or []) if s] or ([recommended_action] if recommended_action else [])
        if not steps:
            return {"error": "Rejected: give at least one concrete step the user can follow."}
        validated: list[dict[str, Any]] = []
        for ev in evidence or []:
            table = ev.get("table")
            model = EVIDENCE_TABLES.get(table or "")
            ids = []
            for rid in ev.get("record_ids") or []:
                try:
                    u = uuid.UUID(str(rid))
                except ValueError:
                    continue
                if model is not None and self.db.get(model, u) is not None:
                    ids.append(str(u))
            if model is None or not ids:
                continue
            validated.append({"table": table, "record_ids": ids, "summary": ev.get("summary", ""),
                              "measurement_type": "first_party" if table in ("search_observations", "analytics_events") else "observed"})
        if not validated:
            return {"error": "Rejected: no valid evidence record ids. Use ids returned by the get_* tools."}
        key = f"ai:{uuid.uuid5(uuid.NAMESPACE_URL, title.lower().strip())}"
        draft = Draft(key=key, section="fix", category=category, title=title[:300],
                      why=why or description or "", steps=steps[:6],
                      impact=float(impact), effort=int(effort), confidence=float(confidence),
                      suggestions={k: v for k, v in (("description", description), ("recommended_action", recommended_action)) if v},
                      evidence=validated, origin="ai", source="ai_analyst",
                      target_urls=target_urls or [], target_keywords=target_keywords or [])
        item = sync_one(self.db, self.project.id, draft)
        self.created.append(str(item.id))
        return {"ok": True, "plan_item_id": str(item.id), "priority": item.priority,
                "where": "Growth Plan → Fix once"}

    def tool_update_action_status(self, action_id: str, status: str, note: str | None = None) -> dict[str, Any]:
        action = self.db.get(ActionRecord, uuid.UUID(action_id))
        if action is None or action.project_id != self.project.id:
            return {"error": "action not found"}
        action.status = status
        if status == "in_progress" and not action.started_at:
            action.started_at = datetime.now(UTC)
        if status == "done":
            action.completed_at = datetime.now(UTC)
        if note:
            action.notes = ((action.notes or "") + f"\n[{datetime.now(UTC):%Y-%m-%d}] {note}").strip()
        self.db.commit()
        return {"ok": True}
