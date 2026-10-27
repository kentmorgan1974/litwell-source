# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""Small text helpers shared by the sources, the filters and the scorer."""

from __future__ import annotations

import html
import re
from typing import Dict, List

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean(text) -> str:
    """Plain text from a snippet that may hold HTML / JATS tags and entities."""
    if not text:
        return ""
    t = html.unescape(_TAG.sub(" ", str(text)))
    return _WS.sub(" ", t).strip()


def split_terms(value: str) -> List[str]:
    """'riboflavin, vitamin; HER2' -> ['riboflavin', 'vitamin', 'HER2']."""
    out: List[str] = []
    for part in re.split(r"[,;\n]+", value or ""):
        p = _WS.sub(" ", part).strip().strip('"')
        if p and p.lower() not in (x.lower() for x in out):
            out.append(p)
    return out


def words_of(value: str) -> List[str]:
    return [w for w in re.findall(r"[\w][\w\-']*", value or "") if w]


def _pattern(term: str) -> "re.Pattern[str]":
    """A case-insensitive whole-word pattern; spaces and hyphens in the term
    match either ('B2 protein' also finds 'B2-protein')."""
    pieces = [re.escape(p) for p in re.split(r"[\s\-]+", term.strip()) if p]
    body = r"[\s\-]+".join(pieces)
    return re.compile(r"(?<![\w])" + body + r"(?![\w])", re.IGNORECASE)


_cache: Dict[str, "re.Pattern[str]"] = {}


def has_term(text: str, term: str) -> bool:
    """True when ``term`` occurs in ``text`` as a whole word or phrase."""
    if not text or not term or not term.strip():
        return False
    pat = _cache.get(term)
    if pat is None:
        pat = _cache[term] = _pattern(term)
    return pat.search(text) is not None
