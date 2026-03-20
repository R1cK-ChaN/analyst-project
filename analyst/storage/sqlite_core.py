from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from analyst.contracts import normalize_utc_iso, to_epoch_ms

def default_engine_db_path(root: Path | None = None) -> Path:
    base = root or Path.cwd()
    return base / ".analyst" / "engine.db"

def _matches_scope_tags(text: str, tags: list[str]) -> bool:
    lowered = text.lower()
    return any(re.search(rf"\b{re.escape(tag.lower())}\b", lowered) for tag in tags)

def _safe_epoch_ms(value: str | datetime | None) -> int:
    if value in (None, ""):
        return 0
    try:
        return to_epoch_ms(value)
    except (TypeError, ValueError):
        return 0

def _safe_utc_iso(value: str | datetime | None) -> str:
    if value in (None, ""):
        return ""
    try:
        return normalize_utc_iso(value)
    except (TypeError, ValueError):
        return str(value)

def _infer_timestamp_precision(value: str | None) -> str:
    if not value:
        return "estimated"
    if re.search(r"[T ]\d{1,2}:\d{2}", value):
        return "exact"
    return "date_only"

