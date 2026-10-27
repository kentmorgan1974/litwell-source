# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""Optional AI triage with a local Ollama model (free, offline).

Off by default. Nothing is sent anywhere except to the Ollama server on this
computer: a non-local address in the settings is refused. If Ollama is not
installed or not running, :func:`triage` returns a one-line note and the search
carries on without it.

For each record the model sees the title and abstract plus the active profile's
plain-language description and answers with a rating (Relevant / Maybe / Not
relevant) and a one-line reason.
"""

from __future__ import annotations

import json
import re
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from .models import Article

DEFAULT_URL = "http://localhost:11434"
RATINGS = ("Relevant", "Maybe", "Not relevant")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}

_SYSTEM = (
    "You help a researcher screen search results. Judge ONLY from the title and "
    "abstract you are given, against the description of what the researcher wants. "
    'Reply with JSON only: {"rating": "Relevant" | "Maybe" | "Not relevant", '
    '"reason": "one short sentence"}. Use "Maybe" when the abstract is missing or unclear.'
)


def _base_url(cfg: Dict) -> str:
    url = (cfg.get("ollama_url") or DEFAULT_URL).strip().rstrip("/")
    host = (urlparse(url).hostname or "").lower()
    if host not in LOCAL_HOSTS:
        raise ValueError(
            f"AI triage only talks to a local Ollama ({host or url} is not this computer)."
        )
    return url


def _installed(cfg: Dict) -> List[Dict]:
    """The models Ollama has pulled, most recently added first. Raises
    requests.RequestException / ValueError when Ollama cannot be reached."""
    r = requests.get(_base_url(cfg) + "/api/tags", timeout=3)
    r.raise_for_status()
    return r.json().get("models", [])


def _is_chat_model(m: Dict) -> bool:
    """Embedding-only models cannot answer a question, so auto-detect skips them."""
    name = (m.get("name") or "").lower()
    family = ((m.get("details") or {}).get("family") or "").lower()
    if re.fullmatch(r"[a-z]+:[0-9a-f]{32,}", name):       # a raw blob alias, not a name anyone chose
        return False
    return "embed" not in name and "bert" not in family


def resolve(cfg: Dict) -> Tuple[Optional[str], str, str]:
    """Pick the model to use. Returns (model, how, problem).

    ``ollama_model`` blank (the default) or "auto" means: use the most recently
    added chat model that is installed. A model named in the setting is used when
    it is installed; when it is not, an installed model is used instead and the
    note says so. ``problem`` is a one-line reason AI triage cannot run ("" if it can).
    """
    try:
        _base_url(cfg)
    except ValueError as exc:
        return None, "", str(exc)
    try:
        have = _installed(cfg)
    except (requests.RequestException, ValueError):
        return None, "", ("AI triage skipped: Ollama is not running on this computer "
                          "(start it, or untick AI triage).")
    names = [m.get("name", "") for m in have if m.get("name")]
    want = (cfg.get("ollama_model") or "").strip()
    if want and want.lower() != "auto":
        for n in names:
            if n == want or (":" not in want and n.split(":")[0] == want):
                return n, "set in settings", ""
    chat = list(dict.fromkeys(m["name"] for m in have if m.get("name") and _is_chat_model(m)))
    if not chat:
        return None, "", ("AI triage skipped: Ollama has no chat model installed "
                          "(for example run: ollama pull llama3.1).")
    if want and want.lower() != "auto":
        return chat[0], "auto-detected", (
            f"the model '{want}' is not installed, so '{chat[0]}' is used instead "
            f"(clear the Ollama model setting to auto-detect without this note)")
    return chat[0], "auto-detected", ""


def check(cfg: Dict) -> Optional[str]:
    """None when AI triage can run, otherwise a one-line reason it cannot."""
    model, _how, problem = resolve(cfg)
    return problem if model is None else None


def _prompt(a: Article, wanted: str) -> str:
    abstract = (a.abstract or "(no abstract available)")[:2500]
    return (
        f"What the researcher wants:\n{wanted}\n\n"
        f"Title: {a.title}\nJournal: {a.journal}\nAbstract: {abstract}\n"
    )


def _parse(text: str):
    try:
        data = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return "", "The model's answer could not be read."
        try:
            data = json.loads(text[start:end + 1])
        except ValueError:
            return "", "The model's answer could not be read."
    rating = str(data.get("rating", "")).strip().lower()
    for r in RATINGS:
        if rating == r.lower():
            return r, " ".join(str(data.get("reason", "")).split())[:300]
    if "not" in rating:
        return "Not relevant", " ".join(str(data.get("reason", "")).split())[:300]
    return "", "The model's answer could not be read."


class Triage:
    """What :func:`triage` did: ``note`` is a one-line problem ("" on success),
    ``model`` the model used and ``how`` why it was chosen."""

    def __init__(self, note: str = "", model: str = "", how: str = "", rated: int = 0) -> None:
        self.note, self.model, self.how, self.rated = note, model, how, rated


def triage(
    arts: Iterable[Article],
    wanted: str,
    cfg: Dict,
    say: Callable[[str], None],
) -> Triage:
    """Rate the records in place with a local model."""
    arts = list(arts)
    model, how, problem = resolve(cfg)
    if model is None:
        return Triage(note=problem)
    base = _base_url(cfg)
    if problem:                       # a named model was missing; another is used
        say(f"AI triage: {problem}.")
    say(f"AI triage uses the local model '{model}' ({how}).")
    limit = int(cfg.get("ai_max_records") or 200)
    timeout = float(cfg.get("ai_timeout") or 120)
    todo = arts[:limit]
    if len(arts) > limit:
        say(f"AI triage rates the best {limit} of {len(arts)} records (setting: ai_max_records).")
    failures = rated = 0
    for i, a in enumerate(todo, start=1):
        say(f"AI triage ({model}): {i} of {len(todo)}…")
        try:
            r = requests.post(
                base + "/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0, "num_predict": 120},
                    "messages": [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": _prompt(a, wanted)},
                    ],
                },
                timeout=timeout,
            )
            r.raise_for_status()
            a.ai_rating, a.ai_reason = _parse(r.json().get("message", {}).get("content", ""))
            rated += 1
            failures = 0
        except (requests.RequestException, ValueError):
            failures += 1
            if failures >= 3:
                return Triage(note="AI triage stopped: Ollama stopped answering.",
                              model=model, how=how, rated=rated)
    return Triage(model=model, how=how, rated=rated)
