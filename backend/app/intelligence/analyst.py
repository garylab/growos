"""Central AI analysis service: one model, tool calling, no multi-agent framework.

The analyst can only see normalized data through tools, and anything it finds is written into the user's Growth Plan
with evidence that references real records.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.adapters.ai.common import ChatTurn
from app.intelligence.tools import TOOL_SPECS, ToolRunner
from app.models import Project, ProviderConnection
from app.services.providers import ProviderNotConfigured, build_adapter, list_connections_for, record_usage, usage_tokens

ANALYST_PROVIDERS = ("openai", "gemini", "openai_compatible", "ollama")

SYSTEM_PROMPT = """You are the growth analyst inside GrowOS, a customer-acquisition intelligence platform.
Your job: find concrete, evidence-backed things the brand "{brand}" ({description}) should do, and add them to the
user's Growth Plan.

How your output reaches the user — read this twice:
The prose you write is NOT shown to anyone. The ONLY thing the user ever sees is the items you create by calling
add_plan_item. A finding you describe in text but do not add to the plan is lost. So: for every finding worth acting
on, call add_plan_item. Describing findings in a final message instead of calling the tool means you did nothing.

Rules you must follow:
1. Call get_plan first, then the get_* tools you need. Never assume data that the tools did not return.
2. If an integration has no data (e.g. "not connected"), say so; do not invent metrics.
3. Only add an item when you can cite specific record ids returned by the get_* tools.
4. Do not repeat anything already on the checklist. The rule engine covers the obvious findings, so look for the
   cross-module insight it would miss (e.g. a query with real Search Console demand where AI answers recommend a competitor).
5. Impact 0-100, confidence 0-1, effort 1-5. Put the numbers from the evidence into "why".
6. Add between one and five items. Quality over quantity — but at least one, unless the data genuinely shows nothing.
Only after the add_plan_item calls have returned, reply with one short paragraph naming what you added."""


def pick_analyst_connection(db: Session, project_id: uuid.UUID) -> ProviderConnection:
    conns = [c for c in list_connections_for(db, project_id, "ai") if c.provider_key in ANALYST_PROVIDERS]
    if not conns:
        raise ProviderNotConfigured("No AI provider suitable for analysis is configured (OpenAI, Gemini, Ollama or OpenAI-compatible).")
    preferred = [c for c in conns if (c.config or {}).get("use_for_analysis")]
    return (preferred or conns)[0]


def run_analysis(db: Session, project: Project, *, focus: str | None = None, max_turns: int = 12,
                 job_id: uuid.UUID | None = None, on_progress: Callable[[int, str], None] | None = None) -> dict[str, Any]:
    conn = pick_analyst_connection(db, project.id)
    adapter = build_adapter(conn)
    runner = ToolRunner(db, project)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT.format(brand=project.brand_name, description=project.description or "no description")},
        {"role": "user", "content": focus or "Analyze all available data and add the most valuable actions you can support with evidence to the plan."},
    ]
    transcript: list[dict[str, Any]] = []
    total_in = total_out = 0
    final_text = None
    for turn in range(max_turns):
        if on_progress:
            on_progress(int(90 * turn / max_turns), f"Analyst turn {turn + 1}")
        result: ChatTurn = adapter.chat(messages, tools=TOOL_SPECS)  # type: ignore[attr-defined]
        tin, tout = usage_tokens(result.usage)
        total_in, total_out = total_in + tin, total_out + tout
        messages.append(result.raw_message if conn.provider_key == "gemini" else {"role": "assistant", "content": result.text,
                                                                                   **({"tool_calls": result.raw_message.get("tool_calls")} if result.raw_message.get("tool_calls") else {})})
        if not result.tool_calls:
            final_text = result.text
            transcript.append({"turn": turn, "assistant": result.text})
            break
        for call in result.tool_calls:
            output = runner.run(call.name, call.arguments)
            transcript.append({"turn": turn, "tool": call.name, "arguments": call.arguments, "result_preview": output[:500]})
            messages.append(adapter.tool_result_message(call, output))  # type: ignore[attr-defined]
    record_usage(db, project_id=project.id, provider_key=conn.provider_key, operation="ai_analysis", connection_id=conn.id,
                 job_id=job_id, units=total_in + total_out, unit_type="tokens", tokens_in=total_in, tokens_out=total_out,
                 details={"model": adapter.config.get("analysis_model") or adapter.config.get("model")})
    db.commit()
    return {"provider": conn.provider_key, "model": adapter.config.get("analysis_model") or adapter.config.get("model"),
            "summary": final_text, "plan_items_created": runner.created, "turns": len(transcript),
            "tokens": {"in": total_in, "out": total_out}, "transcript": transcript}
