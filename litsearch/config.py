# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""Local configuration persisted between runs.

Stored as JSON in the user's home directory so it works identically on
Windows and macOS without any OS-specific path handling.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

CONFIG_PATH = Path.home() / ".litsearch_config.json"

DEFAULTS: Dict[str, Any] = {
    "excel_path": "",       # master .xlsx file chosen by the user
    "contact_email": "",    # optional; Crossref / OpenAlex / NCBI "polite pool". Blank by default,
                            # stored only in this file on this computer, never sent anywhere else.
    "ncbi_email": "",       # older name for contact_email; still read if contact_email is blank
    "ncbi_api_key": "",     # optional, raises NCBI rate limit from 3 to 10 req/s
    "uspto_api_key": "",        # USPTO Open Data Portal key (US patents)
    "patentsview_api_key": "",  # legacy name for the same key; still read
    "openalex_api_key": "",     # optional free key: own daily budget on OpenAlex
    "epo_ops_key": "",          # EPO OPS consumer key (worldwide patents)
    "epo_ops_secret": "",       # EPO OPS consumer secret
    "default_source": "pubmed",   # first ticked source (older versions read only this)
    "default_sources": [],        # every ticked source; empty = just default_source
    "max_results": 100,
    "startup_prompt": True,  # ask "continue / new file" when a file already has data
    # Remembered form values
    "match_mode": "exact",   # "exact", "all" or "any"
    "must_terms": "",
    "exclude_terms": "",
    "min_score": 0,
    "last_profile": "",
    # Named search profiles (two deletable examples are added once)
    "profiles": {},
    "profiles_seeded": False,
    # Optional AI triage with a local Ollama model (free, offline, off by default)
    "ai_enabled": False,
    "ollama_model": "",               # blank = auto-detect an installed model; or name one you have pulled
    "ollama_url": "http://localhost:11434",   # must be this computer
    "ai_max_records": 200,
    "ai_timeout": 120,
}


def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: data[k] for k in data if k in DEFAULTS})
    except (OSError, ValueError):
        # Corrupt or unreadable config should never stop the app starting.
        pass
    if not str(cfg.get("contact_email") or "").strip() and str(cfg.get("ncbi_email") or "").strip():
        cfg["contact_email"] = cfg["ncbi_email"]      # settings from versions before 1.4
    if not isinstance(cfg.get("profiles"), dict):
        cfg["profiles"] = {}
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    clean = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
    clean["ncbi_email"] = ""      # superseded by contact_email
    try:
        CONFIG_PATH.write_text(
            json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as exc:  # pragma: no cover - surfaced to the UI by caller
        raise RuntimeError(f"Could not save config to {CONFIG_PATH}: {exc}") from exc


def selected_sources(cfg: Dict[str, Any], valid) -> list:
    """The sources to tick at startup: ``default_sources`` if it names any valid
    source, otherwise the single ``default_source`` (settings from older versions)."""
    wanted = cfg.get("default_sources")
    if isinstance(wanted, list):
        keep = [k for k in wanted if k in valid]
        if keep:
            return keep
    one = cfg.get("default_source")
    return [one] if one in valid else [next(iter(valid))]
