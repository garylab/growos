"""Raw artifact storage on the local filesystem (persistent volume). Provenance for every collected record."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings


def artifacts_root() -> Path:
    root = Path(get_settings().artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def store_bytes(project_id: uuid.UUID | str, kind: str, data: bytes, ext: str) -> tuple[str, str, int]:
    """Store bytes, return (relative_path, sha256, size)."""
    now = datetime.now(UTC)
    rel_dir = Path(str(project_id)) / kind / now.strftime("%Y/%m/%d")
    (artifacts_root() / rel_dir).mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(data).hexdigest()
    rel_path = rel_dir / f"{now.strftime('%H%M%S')}-{sha[:12]}.{ext}"
    (artifacts_root() / rel_path).write_bytes(data)
    return str(rel_path), sha, len(data)


def store_json(project_id: uuid.UUID | str, kind: str, payload: Any) -> tuple[str, str, int]:
    return store_bytes(project_id, kind, json.dumps(payload, ensure_ascii=False, default=str).encode(), "json")


def read_artifact(rel_path: str) -> bytes:
    path = (artifacts_root() / rel_path).resolve()
    if artifacts_root().resolve() not in path.parents:
        raise ValueError("Invalid artifact path")
    return path.read_bytes()
