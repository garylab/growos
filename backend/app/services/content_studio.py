"""Content studio: turns a checklist topic into a publishable draft.

The generator is whichever AI provider the project has configured. Choosing the Ollama connection keeps everything
open source and on your own hardware — no text leaves the network. Prompts are grounded in the project's own data
(the search query behind the topic, competitors, brand description) so drafts are specific rather than generic.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.intelligence import data as D
from app.models import PlanItem, Project
from app.services.providers import ProviderNotConfigured, build_adapter, list_connections_for, record_usage, usage_tokens

GENERATOR_PROVIDERS = ("openai", "gemini", "openai_compatible", "ollama")

CHANNEL_BRIEF = {
    "blog": "A web article. Markdown with ## headings. 800-1400 words.",
    "linkedin": "A LinkedIn post. 120-200 words, first line is a hook that works as the preview, short paragraphs, no hashtag spam (3 max), ends with a question.",
    "x": "A post for X. Under 280 characters, one idea, no hashtags unless essential. Optionally a 3-5 post thread.",
    "facebook": "A Facebook post. 80-150 words, conversational, one clear call to action.",
    "instagram": "An Instagram caption. 80-150 words, line breaks, 5-10 relevant hashtags at the end.",
    "reddit": "A Reddit post for a relevant subreddit. Genuinely helpful, no marketing voice, discloses affiliation in one line.",
    "newsletter": "A short email. Subject line plus 150-250 words, one link, one call to action.",
    "youtube_short": "A 45-60 second vertical video script.",
    "tiktok": "A 30-45 second vertical video script in a casual, direct voice.",
}

ARTICLE_SCHEMA = """Return ONLY valid JSON:
{"title": "...", "meta_description": "<=155 chars", "slug": "url-slug",
 "body_markdown": "full article in markdown with ## headings",
 "key_takeaway": "the answer in 2-3 sentences, placed near the top so AI assistants can quote it",
 "faq": [{"q": "...", "a": "..."}], "internal_links": ["/suggested-page"], "keywords": ["..."]}"""

SOCIAL_SCHEMA = """Return ONLY valid JSON:
{"posts": [{"channel": "...", "text": "...", "hook": "first line", "hashtags": ["..."], "call_to_action": "..."}],
 "best_time_hint": "...", "notes": "..."}"""

VIDEO_SCHEMA = """Return ONLY valid JSON:
{"title": "...", "hook": "first 3 seconds, spoken", "voiceover": "the full narration, 110-150 words",
 "beats": [{"t": "0-3s", "say": "...", "show": "what is on screen"}],
 "captions": [{"start": "00:00:00,000", "end": "00:00:03,000", "text": "<=7 words"}],
 "shot_list": ["..."], "description": "video description with one link", "hashtags": ["..."],
 "thumbnail_text": "3-5 words"}"""


def pick_generator(db: Session, project_id: uuid.UUID, provider_key: str | None = None):
    conns = [c for c in list_connections_for(db, project_id, "ai") if c.provider_key in GENERATOR_PROVIDERS]
    if provider_key:
        conns = [c for c in conns if c.provider_key == provider_key]
    if not conns:
        raise ProviderNotConfigured(
            "No AI provider is configured for writing. Add OpenAI or Gemini under Integrations — or Ollama to keep "
            "generation fully open source and local.")
    preferred = [c for c in conns if (c.config or {}).get("use_for_analysis")]
    return (preferred or conns)[0]


def topic_context(db: Session, project: Project, topic: str, plan_item: PlanItem | None) -> dict[str, Any]:
    """Facts from the project's own data that make the draft specific."""
    ctx: dict[str, Any] = {"brand": project.brand_name, "description": project.description,
                           "language": project.default_language, "country": project.default_country,
                           "competitors": [c.name for c in D.competitors(db, project.id)][:6]}
    evidence: list[dict[str, Any]] = []
    for d in D.primary_domains(db, project.id):
        ctx.setdefault("website", d.base_url)
        if D.gsc_available(db, d.id):
            rows = [r for r in D.gsc_query_page_rows(db, d.id, 90, 1, 2000) if topic.lower() in r["query"].lower()]
            if rows:
                best = max(rows, key=lambda r: r["impressions"])
                ctx["search_demand"] = {"query": best["query"], "impressions": best["impressions"],
                                        "position": round(best["position"], 1), "existing_page": best["page"]}
                evidence.append({"table": "search_observations", "summary":
                                 f"“{best['query']}” had {best['impressions']} impressions at position {best['position']:.0f} in 90 days",
                                 "record_ids": best["ids"][:10]})
    if plan_item is not None:
        sugg = plan_item.suggestions or {}
        for t in (sugg.get("topics") or []):
            if t.get("topic", "").lower() == topic.lower():
                ctx["why_this_topic"] = t.get("reason")
                ctx["outline"] = t.get("outline")
                evidence.append({"table": "plan_items", "summary": t.get("reason", ""), "record_ids": [str(plan_item.id)]})
                break
        for p in (sugg.get("prompts") or []):
            if isinstance(p, dict) and p.get("prompt", "").lower() == topic.lower():
                ctx["ai_prompt"] = {"prompt": p.get("prompt"), "competitors_recommended": p.get("competitors")}
                ctx["outline"] = p.get("outline")
                break
    return {"context": ctx, "evidence": evidence}


def _prompt(kind: str, channel: str, topic: str, ctx: dict[str, Any], notes: str | None) -> list[dict[str, str]]:
    schema = {"article": ARTICLE_SCHEMA, "social_post": SOCIAL_SCHEMA, "video_script": VIDEO_SCHEMA}[kind]
    brief = CHANNEL_BRIEF.get(channel, CHANNEL_BRIEF["blog"])
    system = (
        "You are a senior content writer for a B2B/B2C brand. You write specific, useful content that a knowledgeable "
        "reader respects: concrete examples, no filler, no hype, no invented statistics. If you do not know a fact, "
        "leave a clearly marked placeholder like [verify: ...] rather than making it up. Match the requested language.")
    user = (
        f"Brand: {ctx.get('brand')}\n"
        f"What the business does: {ctx.get('description') or '(not provided)'}\n"
        f"Website: {ctx.get('website') or '(not provided)'}\n"
        f"Competitors: {', '.join(ctx.get('competitors') or []) or '(none tracked)'}\n"
        f"Language: {ctx.get('language')} | Audience country: {ctx.get('country')}\n\n"
        f"TOPIC: {topic}\n"
        + (f"Why this topic matters: {ctx['why_this_topic']}\n" if ctx.get("why_this_topic") else "")
        + (f"Search demand: {json.dumps(ctx['search_demand'])}\n" if ctx.get("search_demand") else "")
        + (f"AI assistants are asked this and currently recommend: {json.dumps(ctx['ai_prompt'])}\n" if ctx.get("ai_prompt") else "")
        + (f"Suggested outline to follow: {json.dumps(ctx['outline'])}\n" if ctx.get("outline") else "")
        + (f"Extra instructions from the user: {notes}\n" if notes else "")
        + f"\nFormat: {brief}\n{schema}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _parse_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except ValueError:
            pass
    return {"body_markdown": text, "title": None, "_unparsed": True}


def to_srt(captions: list[dict[str, Any]]) -> str:
    lines = []
    for n, c in enumerate(captions or [], start=1):
        lines.append(f"{n}\n{c.get('start', '00:00:00,000')} --> {c.get('end', '00:00:03,000')}\n{c.get('text', '')}\n")
    return "\n".join(lines)


def generate(db: Session, project: Project, *, kind: str, topic: str, channel: str = "blog",
             plan_item: PlanItem | None = None, notes: str | None = None, provider_key: str | None = None,
             job_id: uuid.UUID | None = None) -> dict[str, Any]:
    conn = pick_generator(db, project.id, provider_key)
    adapter = build_adapter(conn)
    built = topic_context(db, project, topic, plan_item)
    messages = _prompt(kind, channel, topic, built["context"], notes)
    turn = adapter.chat(messages)  # type: ignore[attr-defined]
    payload = _parse_json(turn.text or "")
    tin, tout = usage_tokens(turn.usage)
    model = adapter.config.get("analysis_model") or adapter.config.get("model")
    record_usage(db, project_id=project.id, provider_key=conn.provider_key, operation=f"content:{kind}",
                 connection_id=conn.id, job_id=job_id, units=tin + tout, unit_type="tokens",
                 tokens_in=tin, tokens_out=tout, details={"model": model, "channel": channel})

    title = payload.get("title")
    if kind == "article":
        body = payload.get("body_markdown") or ""
        assets = {k: payload.get(k) for k in ("meta_description", "slug", "key_takeaway", "faq", "internal_links", "keywords") if payload.get(k)}
    elif kind == "social_post":
        posts = payload.get("posts") or []
        body = "\n\n---\n\n".join(f"[{p.get('channel', channel)}]\n{p.get('text', '')}" for p in posts) or payload.get("text", "")
        assets = {"posts": posts, "best_time_hint": payload.get("best_time_hint"), "notes": payload.get("notes")}
        title = title or f"{channel} post: {topic[:60]}"
    else:
        body = payload.get("voiceover") or ""
        assets = {k: payload.get(k) for k in ("hook", "beats", "captions", "shot_list", "description", "hashtags", "thumbnail_text") if payload.get(k)}
        assets["srt"] = to_srt(payload.get("captions") or [])
        assets["render_hint"] = ("Render with open-source tools: ffmpeg or MoviePy for the cut, Piper or Coqui TTS for the "
                                 "voiceover, and the SRT above for burned-in captions.")
    if payload.get("_unparsed"):
        assets["warning"] = "The model did not return structured JSON; the raw text is in the body."
    return {"title": title, "body": body, "assets": assets, "evidence": built["evidence"],
            "provider_key": conn.provider_key, "model": model, "context": built["context"]}
