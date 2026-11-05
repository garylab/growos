"""Competitor (and own) page change detection for watched URLs such as pricing or feature pages."""
from __future__ import annotations

import difflib
import hashlib
import re
from typing import Any

from sqlalchemy import select

from app.core.content_extract import main_text
from app.core.safe_http import UnsafeURLError, safe_get
from app.models import CompetitorObservation, Domain
from app.tasks.context import TaskContext
from app.tasks.registry import task

PRICE_RE = re.compile(r"(?:[$€£]\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|GBP|/mo|/month|/year|per month|per user))", re.I)


def extract_text(html: str, url: str | None = None) -> tuple[str | None, str]:
    """(title, main content) — boilerplate removed, so a change means the content changed.

    Delegated to `app.core.content_extract`: comparing full page text flagged a change whenever a cookie banner,
    a testimonial carousel or a "latest posts" rail moved, which is most runs on most sites.
    """
    extracted = main_text(html, url)
    return extracted.title, extracted.text


@task("watch_competitor_pages", "Fetch watched pages and detect content/pricing changes")
def watch_competitor_pages(ctx: TaskContext) -> dict[str, Any]:
    domains = ctx.db.scalars(select(Domain).where(Domain.project_id == ctx.project_id, Domain.is_active.is_(True))).all()
    targets = [(d, u) for d in domains for u in (d.watch_urls or [])]
    if ctx.params.get("include_home"):
        targets += [(d, d.base_url) for d in domains if d.role == "competitor"]
    changed, errors, total = 0, [], len(targets)
    for i, (domain, url) in enumerate(targets):
        ctx.progress(int(95 * i / max(1, total)), f"Fetching {url}")
        try:
            resp = safe_get(url)
        except (UnsafeURLError, Exception) as exc:  # noqa: BLE001
            errors.append({"url": url, "error": str(exc)[:300]})
            continue
        title, text = extract_text(resp.text, url) if "html" in resp.headers.get("content-type", "") else (None, resp.text[:200000])
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        artifact = ctx.save_artifact("safe_fetch", "watched_page", resp.content, content_type=resp.headers.get("content-type", "text/html"),
                                     meta={"url": url, "status": resp.status_code, "final_url": resp.final_url}, ext="html")
        prev = ctx.db.scalar(select(CompetitorObservation).where(CompetitorObservation.project_id == ctx.project_id,
                                                                 CompetitorObservation.url == url)
                             .order_by(CompetitorObservation.observed_at.desc()).limit(1))
        obs = CompetitorObservation(project_id=ctx.project_id, competitor_id=domain.competitor_id, domain_id=domain.id,
                                    job_id=ctx.job.id, artifact_id=artifact.id, url=url, status_code=resp.status_code,
                                    content_hash=content_hash, title=title, text_length=len(text),
                                    previous_observation_id=prev.id if prev else None)
        if prev is not None and prev.content_hash != content_hash:
            # The stored hash and this one can disagree for a reason that is not a content change: the previous
            # observation may have been extracted by an older version of `extract_text`. `_previous_text`
            # re-extracts the archived HTML with today's extractor, so the diff below is apples to apples even
            # when the hashes are not, and it — not the hash — decides whether anything actually changed.
            prev_text = _previous_text(ctx, prev)
            diff = _diff_summary(prev_text, text)
            really_changed = diff["change_ratio"] > 0 if prev_text else True
            obs.changed = really_changed
            obs.change_ratio = diff["change_ratio"]
            obs.diff_summary = diff
            changed += 1 if really_changed else 0
        ctx.db.add(obs)
        ctx.db.commit()
    return {"watched": total, "changed": changed, "errors": errors}


def _previous_text(ctx: TaskContext, prev: CompetitorObservation) -> str:
    from app.core.artifacts import read_artifact
    from app.models import RawArtifact
    if prev.artifact_id:
        art = ctx.db.get(RawArtifact, prev.artifact_id)
        if art:
            try:
                html = read_artifact(art.storage_path).decode("utf-8", errors="replace")
                return extract_text(html, prev.url)[1]
            except (OSError, ValueError):
                pass
    return ""


def _diff_summary(old: str, new: str) -> dict[str, Any]:
    old_lines, new_lines = old.splitlines(), new.splitlines()
    sm = difflib.SequenceMatcher(None, old_lines, new_lines)
    added, removed = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):
            removed.extend(old_lines[i1:i2])
        if tag in ("replace", "insert"):
            added.extend(new_lines[j1:j2])
    old_prices, new_prices = set(PRICE_RE.findall(old)), set(PRICE_RE.findall(new))
    return {"change_ratio": round(1 - sm.ratio(), 4), "added": added[:40], "removed": removed[:40],
            "added_count": len(added), "removed_count": len(removed),
            "prices_added": sorted(new_prices - old_prices)[:20], "prices_removed": sorted(old_prices - new_prices)[:20]}
