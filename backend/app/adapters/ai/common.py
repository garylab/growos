"""Shared types for AI provider adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


@dataclass
class Citation:
    url: str
    domain: str
    title: str | None = None


@dataclass
class AIAnswer:
    text: str
    model: str
    model_version: str | None
    grounded: bool
    grounding_type: str
    citations: list[Citation]
    usage: dict[str, Any]
    latency_ms: int
    request_config: dict[str, Any] = field(default_factory=dict)
    raw: Any = None


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatTurn:
    """Result of one model call in a tool-calling loop."""
    text: str | None
    tool_calls: list[ToolCall]
    usage: dict[str, Any]
    raw_message: Any  # provider-specific assistant message to append to history


def domain_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def dedupe_citations(items: list[Citation]) -> list[Citation]:
    seen: set[str] = set()
    out: list[Citation] = []
    for c in items:
        if c.url and c.url not in seen:
            seen.add(c.url)
            out.append(c)
    return out
