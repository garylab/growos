"""Submission targets: sync the awesome-submitlist dataset and recommend relevant places for a project.

Matching is hybrid. Each target carries an embedding of its text (name + audience + description + categories).
A project carries a cached embedding of its profile (brand + description + keywords) and a short list of
category tags classified from the dataset's own category vocabulary. Recommendations blend semantic similarity,
lexical audience overlap, category fit and domain authority. With no embedding key, it degrades to lexical + tags.
"""
from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Keyword, Project, SubmissionTarget
from app.services.embeddings import batch_size, cosine, embed_texts, embeddings_available

log = get_logger("destinations")

DEST_URL = "https://raw.githubusercontent.com/alvinunreal/awesome-submitlist/refs/heads/main/data/destinations.json"
_FIELDS = ("name", "type", "website_url", "submission_url", "logo_url", "description", "audience",
           "eligibility", "pricing", "pricing_note", "link_type", "domain_rating", "monthly_traffic",
           "categories", "subreddit")
_STOP = {"the", "and", "for", "with", "your", "you", "our", "that", "this", "are", "from", "all", "any",
         "community", "relevant", "creators", "working", "subject", "posting", "restrictions", "apply",
         "seeking", "looking", "people", "users", "tool", "tools", "product", "products", "site", "sites",
         "company", "companies", "business", "businesses", "platform", "service", "services", "app", "apps"}
_CATEGORY_CACHE: dict[str, list[float]] = {}  # category label -> embedding, process-local


def _ints(v: Any) -> int | None:
    try:
        return int(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _target_text(r: dict[str, Any]) -> str:
    return " ".join(filter(None, [r.get("name"), r.get("audience"), r.get("description"),
                                  " ".join(r.get("categories") or [])]))[:8000]


def sync_destinations(db: Session, *, force: bool = False, url: str = DEST_URL) -> dict[str, Any]:
    """Fetch the dataset and upsert it by slug, then embed any targets missing an embedding.

    Skips the fetch if one ran in the last 25 days unless `force`, but still back-fills missing embeddings.
    """
    last = db.scalar(select(func.max(SubmissionTarget.synced_at)))
    skip = bool(last and not force and (datetime.now(UTC) - last) < timedelta(days=25))
    synced = 0
    if not skip:
        resp = httpx.get(url, timeout=90, follow_redirects=True)
        resp.raise_for_status()
        rows = (resp.json() or {}).get("destinations") or []
        now = datetime.now(UTC)
        seen: set[str] = set()
        batch: list[dict[str, Any]] = []
        for r in rows:
            slug = (r.get("slug") or "").strip()
            if not slug or slug in seen:
                continue
            seen.add(slug)
            batch.append({"slug": slug, "synced_at": now,
                          "name": (r.get("name") or slug)[:300], "type": (r.get("type") or "unknown")[:40],
                          "website_url": r.get("website_url"), "submission_url": r.get("submission_url"),
                          "logo_url": r.get("logo_url"), "description": r.get("description"), "audience": r.get("audience"),
                          "eligibility": r.get("eligibility"), "pricing": (r.get("pricing") or None),
                          "pricing_note": r.get("pricing_note"), "link_type": (r.get("link_type") or None),
                          "domain_rating": _ints(r.get("domain_rating")), "monthly_traffic": _ints(r.get("monthly_traffic")),
                          "categories": r.get("categories") or [], "subreddit": r.get("subreddit")})
        for i in range(0, len(batch), 500):
            chunk = batch[i:i + 500]
            stmt = insert(SubmissionTarget).values(chunk)
            # Update the data fields but keep any existing embedding; new rows get embedded below.
            stmt = stmt.on_conflict_do_update(index_elements=["slug"],
                                              set_={k: getattr(stmt.excluded, k) for k in (*_FIELDS, "synced_at")})
            db.execute(stmt)
        if seen:
            db.execute(delete(SubmissionTarget).where(SubmissionTarget.slug.not_in(seen)))
        db.commit()
        synced = len(seen)

    embedded = _embed_missing_targets(db)
    log.info("destinations.synced", synced=synced, embedded=embedded, skipped=skip)
    have = db.scalar(select(func.count()).select_from(SubmissionTarget)) or 0
    return {"synced": synced, "embedded": embedded, "skipped": skip, "count": have}


def backfill_embeddings(db: Session, *, limit: int = 4000) -> dict[str, Any]:
    """Embed as many still-unembedded targets as the quota allows this run. Safe to call on a short interval:
    it stops cleanly when the embedding API rate-limits, so a daily-capped free tier fills in over several runs."""
    before = db.scalar(select(func.count()).select_from(SubmissionTarget).where(SubmissionTarget.embedding.is_(None))) or 0
    done = _embed_missing_targets(db, limit=limit)
    return {"embedded": done, "remaining": max(0, before - done)}


def _embed_missing_targets(db: Session, *, limit: int = 4000) -> int:
    """Embed targets that have none yet. No-op without an embedding key."""
    if not embeddings_available(db):
        return 0
    rows = list(db.scalars(select(SubmissionTarget).where(SubmissionTarget.embedding.is_(None)).limit(limit)).all())
    if not rows:
        return 0
    done = 0
    bs = batch_size()
    for i in range(0, len(rows), bs):
        chunk = rows[i:i + bs]
        vecs = embed_texts(db, [_target_text({"name": t.name, "audience": t.audience, "description": t.description,
                                             "categories": t.categories}) for t in chunk])
        if not vecs:
            break  # failed; progress so far is saved and the next run resumes
        for t, v in zip(chunk, vecs):
            t.embedding = v
        db.commit()
        done += len(chunk)
    return done


# ------------------------------------------------------------------ project profile & recommendation
def _project_terms(db: Session, project: Project) -> set[str]:
    words = re.findall(r"[a-z0-9]+", _project_profile_text(db, project).lower())
    return {w for w in words if len(w) >= 4 and w not in _STOP}


def _project_profile_text(db: Session, project: Project) -> str:
    kws = db.scalars(select(Keyword.text).where(Keyword.project_id == project.id).limit(40)).all()
    return " ".join(filter(None, [project.brand_name, project.name, project.description, *kws]))


def _category_vocab(db: Session) -> list[str]:
    rows = db.execute(select(func.unnest(SubmissionTarget.categories)).distinct()).all()
    return sorted({r[0] for r in rows if r[0]})


def ensure_project_profile(db: Session, project: Project) -> None:
    """Refresh the project's cached embedding and category tags when its profile text changes. No-op w/o a key."""
    if not embeddings_available(db):
        return
    text = _project_profile_text(db, project)
    digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
    if project.profile_embedding and project.profile_hash == digest:
        return
    res = embed_texts(db, [text])
    emb = res[0] if res else None
    if not emb:
        return
    project.profile_embedding = emb
    project.profile_hash = digest
    project.profile_embedded_at = datetime.now(UTC)
    # Classify into the dataset's category vocabulary by nearest label embedding.
    vocab = _category_vocab(db)
    missing = [c for c in vocab if c not in _CATEGORY_CACHE]
    if missing:
        vecs = embed_texts(db, missing)
        if vecs:
            _CATEGORY_CACHE.update(dict(zip(missing, vecs)))
    # The dataset's category vocabulary is tech-centric, so a nearest-label classification is only meaningful for
    # tech brands and is unreliable for everything else. We keep the closest few tags for reference but do NOT let
    # them steer ranking — the target embeddings already encode each place's categories, so semantic similarity
    # covers category fit without this blunt instrument.
    scored = sorted(((c, cosine(emb, _CATEGORY_CACHE.get(c))) for c in vocab), key=lambda cs: -cs[1])
    top = scored[0][1] if scored else 0.0
    project.category_tags = [c for c, s in scored if s >= top - 0.02][:3]
    db.commit()


def _row(d: SubmissionTarget) -> dict[str, Any]:
    return {"slug": d.slug, "name": d.name, "type": d.type, "website_url": d.website_url,
            "submission_url": d.submission_url, "logo_url": d.logo_url, "description": d.description,
            "audience": d.audience, "pricing": d.pricing, "pricing_note": d.pricing_note,
            "link_type": d.link_type, "domain_rating": d.domain_rating, "monthly_traffic": d.monthly_traffic,
            "categories": d.categories, "subreddit": d.subreddit}


def _lexical(d: SubmissionTarget, terms: set[str]) -> int:
    if not terms:
        return 0
    aud = (d.audience or "").lower()
    rest = f"{d.description or ''} {' '.join(d.categories or [])}".lower()
    return 2 * sum(1 for t in terms if t in aud) + sum(1 for t in terms if t in rest)


def recommend_for_project(db: Session, project: Project, *, limit: int = 40,
                          audience: str | None = None, q: str | None = None, want_type: str | None = None) -> dict[str, Any]:
    """Hybrid-ranked submission targets for a project; subreddits collapsed into one expandable group."""
    total = db.scalar(select(func.count()).select_from(SubmissionTarget)) or 0
    if not total:
        return {"available": False, "destinations": [], "reddit": {"count": 0, "subreddits": []}, "audiences": [], "total": 0}

    filtered = bool(audience or q or want_type)
    stmt = select(SubmissionTarget)
    if audience:
        stmt = stmt.where(func.lower(SubmissionTarget.audience).like(f"%{audience.lower()}%"))
    if want_type:
        stmt = stmt.where(SubmissionTarget.type == want_type)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(SubmissionTarget.name).like(like)
                          | func.lower(func.coalesce(SubmissionTarget.audience, "")).like(like)
                          | func.lower(func.coalesce(SubmissionTarget.description, "")).like(like))
    rows = list(db.scalars(stmt).all())

    if filtered:
        ranked = sorted(rows, key=lambda d: (-(d.domain_rating or 0), d.name))
    else:
        ensure_project_profile(db, project)
        terms = _project_terms(db, project)
        pemb = project.profile_embedding
        lex = {d.slug: _lexical(d, terms) for d in rows}
        maxlex = max(lex.values() or [1]) or 1

        # Semantic similarity (target embedding vs project profile) is the primary signal; lexical audience overlap
        # is the secondary; domain authority is only a small tiebreak. Category fit is already inside the embedding.
        def blended(d: SubmissionTarget) -> float:
            lx = lex[d.slug] / maxlex
            dr = (d.domain_rating or 0) / 100
            if pemb and d.embedding:
                return 0.7 * cosine(pemb, d.embedding) + 0.3 * lx + 0.05 * dr
            return lx + 0.05 * dr

        scored = sorted(((d, blended(d)) for d in rows), key=lambda ds: -ds[1])
        ranked = [d for d, s in scored if s > 0.0] or sorted(
            [d for d in rows if d.type in ("directory", "citation", "marketplace")],
            key=lambda d: (-(d.domain_rating or 0), d.name))

    subs = [d for d in ranked if d.type == "subreddit"]
    others = [d for d in ranked if d.type != "subreddit"][:limit]
    audiences = sorted({(d.audience or "").split(".")[0].strip() for d in rows if d.audience})[:60]
    return {
        "available": True, "total": total, "filtered": filtered,
        "matched_tags": sorted(project.category_tags or []),
        "destinations": [_row(d) for d in others],
        "reddit": {"count": len(subs), "subreddits": [_row(d) for d in subs[:200]]},
        "audiences": audiences,
    }
