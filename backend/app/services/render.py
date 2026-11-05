"""The optional JavaScript renderer, resolved from a provider connection.

Page inspection lives in `app.services.page_signals` / `page_inspect`, which take a plain `Renderer` callable and
know nothing about the database or providers. This is the piece that bridges the two: if a SerpApi Extract
connection is enabled for the project, these return its `render_html` plus the per-job page ceiling from its
config; otherwise they return `None` and the inspectors behave exactly as they always have.
"""
from __future__ import annotations

import uuid

from app.services.page_signals import Renderer
from app.services.providers import build_adapter, find_connection

RENDER_PROVIDER = "serpapi_extract"


def get_renderer(db, project_id: uuid.UUID | None) -> tuple[Renderer | None, int]:
    """(renderer, pages it may spend) — (None, 0) when no renderer is connected.

    A broken provider must never break a crawl, so a connection that cannot be built is treated as absent.
    """
    conn = find_connection(db, project_id, RENDER_PROVIDER)
    if conn is None:
        return None, 0
    try:
        adapter = build_adapter(conn)
    except Exception:  # noqa: BLE001
        return None, 0
    return adapter.render_html, adapter.page_budget  # type: ignore[attr-defined]
