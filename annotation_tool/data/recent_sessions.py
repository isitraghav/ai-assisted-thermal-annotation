"""Persist and load recently opened project sessions."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

MAX_RECENT = 10
_CONFIG_DIR = Path.home() / ".config" / "thermal-annotation"


def _config_path() -> Path:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return _CONFIG_DIR / "recent_sessions.json"


def load_recent() -> list[dict]:
    p = _config_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def save_recent(entry: dict):
    entries = load_recent()
    entries = [e for e in entries if e.get("output_geojson") != entry.get("output_geojson")]
    entry["last_opened"] = datetime.now().isoformat(timespec="seconds")
    entries.insert(0, entry)
    _config_path().write_text(json.dumps(entries[:MAX_RECENT], indent=2))
