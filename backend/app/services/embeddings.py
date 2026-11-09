"""Text embeddings with a pluggable backend selected by EMBEDDING_PROVIDER.

- local  (default): a small static model (model2vec) baked into the image. No API, no credits, no rate limits.
- openai: text-embedding-3-small, key from OPENAI_API_KEY or an OpenAI provider connection.
- gemini: gemini-embedding-001, key from GEMINI_API_KEY.

Embeddings are global, so any available key is used. Callers degrade to lexical matching when embedding fails.
Vectors from different providers have different sizes, so do not mix providers without re-embedding everything.
"""
from __future__ import annotations

import math

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.secrets import decrypt_credentials
from app.models import ProviderConnection

log = get_logger("embeddings")
LOCAL_MODEL_NAME = "minishlab/potion-base-8M"
_LOCAL = None


def active_provider() -> str:
    return (get_settings().embedding_provider or "local").strip().lower()


def batch_size() -> int:
    return {"local": 1000, "openai": 200, "gemini": 20}.get(active_provider(), 100)


def _local_model():
    global _LOCAL
    if _LOCAL is None:
        from model2vec import StaticModel
        _LOCAL = StaticModel.from_pretrained(LOCAL_MODEL_NAME)
    return _LOCAL


def _api_key(db: Session, provider: str) -> tuple[str | None, str]:
    s = get_settings()
    if provider == "gemini":
        return (s.gemini_api_key or None), "https://generativelanguage.googleapis.com/v1beta"
    # openai: server env first, then a provider connection (global before project-scoped)
    if s.openai_api_key:
        return s.openai_api_key, "https://api.openai.com/v1"
    conns = list(db.scalars(select(ProviderConnection).where(
        ProviderConnection.provider_key == "openai", ProviderConnection.is_enabled.is_(True))).all())
    conns.sort(key=lambda c: c.project_id is not None)
    for c in conns:
        creds = decrypt_credentials(c.credentials_encrypted) or {}
        if creds.get("api_key"):
            return creds["api_key"], (c.config or {}).get("base_url") or "https://api.openai.com/v1"
    return None, "https://api.openai.com/v1"


def embeddings_available(db: Session) -> bool:
    p = active_provider()
    if p == "local":
        try:
            _local_model()
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("embed.local_unavailable", error=str(exc))
            return False
    return bool(_api_key(db, p)[0])


def embed_texts(db: Session, texts: list[str]) -> list[list[float]] | None:
    """Embed one batch, preserving order. Returns None on failure. Caller chooses the batch via batch_size()."""
    if not texts:
        return None
    provider = active_provider()
    clipped = [(t or " ")[:8000] for t in texts]
    try:
        if provider == "local":
            return [list(map(float, v)) for v in _local_model().encode(clipped)]
        key, base = _api_key(db, provider)
        if not key:
            return None
        if provider == "gemini":
            body = {"requests": [{"model": "models/gemini-embedding-001", "content": {"parts": [{"text": t}]}} for t in clipped]}
            r = httpx.post(f"{base}/models/gemini-embedding-001:batchEmbedContents", params={"key": key}, json=body, timeout=60)
            r.raise_for_status()
            embs = r.json().get("embeddings") or []
            vals = [e.get("values") or [] for e in embs]
            return vals if len(vals) == len(texts) else None
        # openai
        r = httpx.post(f"{base.rstrip('/')}/embeddings", headers={"Authorization": f"Bearer {key}"},
                       json={"model": "text-embedding-3-small", "input": clipped}, timeout=60)
        r.raise_for_status()
        data = sorted(r.json().get("data") or [], key=lambda d: d.get("index", 0))
        vals = [d.get("embedding") or [] for d in data]
        return vals if len(vals) == len(texts) else None
    except Exception as exc:  # noqa: BLE001 — never let an embedding failure break the caller
        log.warning("embed.failed", provider=provider, error=str(exc))
        return None


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
