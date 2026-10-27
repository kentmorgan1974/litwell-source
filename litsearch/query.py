# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""Builds the search expressions every source needs from the one set of fields.

Match modes (``SearchParams.match_mode``):

    exact   the keyword is one phrase           "B2 protein"
    all     every word must appear, any order   B2 AND protein
    any     at least one word must appear       B2 OR protein
"""

from __future__ import annotations

from typing import List

from .models import SearchParams
from .textutil import words_of

# Words that carry no meaning of their own in an "all words" / "any word" search.
STOP_WORDS = frozenset(
    "a an and are as at be by for from in is it of on or the to with".split()
)


def keyword_phrase(params: SearchParams) -> str:
    return " ".join((params.keyword or "").split())


def keyword_words(params: SearchParams) -> List[str]:
    """The meaningful words of the keyword (stop words dropped unless that
    would leave nothing)."""
    ws = words_of(keyword_phrase(params))
    keep = [w for w in ws if w.lower() not in STOP_WORDS]
    return keep or ws


def mode(params: SearchParams) -> str:
    return params.match_mode if params.match_mode in ("exact", "all", "any") else "exact"


def quote(text: str) -> str:
    return '"' + text.replace('"', "") + '"'


def expression(params: SearchParams, field_fmt: str, *, and_op: str = " AND ",
               or_op: str = " OR ") -> str:
    """The keyword as a boolean expression.

    ``field_fmt`` is applied to each phrase or word, e.g. ``'{}[Title/Abstract]'``
    for PubMed (it receives a quoted phrase or a bare word)."""
    kw = keyword_phrase(params)
    if not kw:
        return ""
    m = mode(params)
    words = keyword_words(params)
    if m == "exact" or len(words) < 2:
        item = quote(kw) if (m == "exact" and len(words_of(kw)) > 1) else (words[0] if words else kw)
        return field_fmt.format(item)
    joined = (and_op if m == "all" else or_op).join(field_fmt.format(w) for w in words)
    return "(" + joined + ")"
