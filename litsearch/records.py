# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""Combining, filtering and scoring records after they are fetched.

The steps, in the order the search runs them:

1. :func:`merge`    one record per paper, even when several sources returned it;
                    gaps (authors, date, DOI, abstract ...) are filled from the
                    other sources' copies.
2. :func:`enforce`  the exact-phrase / all-words rule for sources that cannot
                    apply it themselves (Crossref ranks by similarity).
3. :func:`filter_records`  "Must also contain" and "Exclude terms".
4. :func:`score`    the rule-based Relevance Score, 0 to 100.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .models import Article, SearchParams, make_dedupe_key
from .query import keyword_phrase, keyword_words, mode
from .textutil import has_term, split_terms

# Sources whose own search does not honour a phrase (Crossref ranks by similarity,
# EPO matches the words loosely); their results are checked against the keyword
# afterwards, on the title and abstract.
ENFORCE_LOCALLY = ("crossref", "epo")


# ---------------------------------------------------------------------------
# 1. merge
# ---------------------------------------------------------------------------
def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def _longer(a: str, b: str) -> str:
    return b if len(b or "") > len(a or "") else a


def absorb(into: Article, other: Article) -> None:
    """Fill the gaps in ``into`` from ``other`` (a copy of the same record)."""
    if not into.authors and other.authors:
        into.authors = list(other.authors)
    if not into.journal:
        into.journal = other.journal
    # A fuller date ("2026-09-08") beats a bare year.
    into.date = _longer(into.date, other.date) if into.date[:4] == other.date[:4] or not into.date else into.date
    if not into.doi:
        into.doi = other.doi
    if not into.link:
        into.link = other.link
    into.abstract = _longer(into.abstract, other.abstract)
    if not into.oa_url:
        into.oa_url = other.oa_url
    if other.citations is not None:
        into.citations = max(into.citations or 0, other.citations)
    if not into.kind:
        into.kind = other.kind
    if not into.title:
        into.title = other.title
    for k in other.sources:
        if k not in into.sources:
            into.sources.append(k)
    if other.source and other.source not in (into.source or ""):
        into.source = "; ".join(x for x in (into.source, other.source) if x)
    if other.score is not None:
        into.score = max(into.score if into.score is not None else 0, other.score)
    if not into.ai_rating and other.ai_rating:
        into.ai_rating, into.ai_reason = other.ai_rating, other.ai_reason
    if other.search_terms and other.search_terms not in (into.search_terms or ""):
        into.search_terms = " | ".join(x for x in (into.search_terms, other.search_terms) if x)
    if not into.search_date:
        into.search_date = other.search_date


class Merger:
    """Groups records that are the same paper (same DOI, or same title)."""

    def __init__(self) -> None:
        self.items: List[Article] = []
        self._by_doi: Dict[str, Article] = {}
        self._by_title: Dict[str, Article] = {}

    def add(self, art: Article) -> bool:
        """Add ``art``; returns True when it was new, False when it was merged
        into a record already held."""
        doi = (art.doi or "").strip().lower()
        nt = _norm_title(art.title)
        hit: Optional[Article] = self._by_doi.get(doi) if doi else None
        if hit is None and nt and len(nt) > 12:
            hit = self._by_title.get(nt)
        if hit is not None:
            had_doi = bool((hit.doi or "").strip())
            absorb(hit, art)
            if doi and not had_doi:
                self._by_doi[doi] = hit
            return False
        self.items.append(art)
        if doi:
            self._by_doi[doi] = art
        if nt and len(nt) > 12:
            self._by_title.setdefault(nt, art)
        return True


def merge(per_source: Sequence[Tuple[str, Sequence[Article]]]) -> List[Article]:
    """``per_source`` is [(source key, records)] in the order the sources were
    asked; the first source to return a paper is the one whose copy is kept."""
    m = Merger()
    for key, arts in per_source:
        for a in arts:
            if key not in a.sources:
                a.sources.append(key)
            m.add(a)
    return m.items


# ---------------------------------------------------------------------------
# 2 + 3. filters
# ---------------------------------------------------------------------------
def _hay(a: Article) -> str:
    return f"{a.title} {a.abstract}"


def phrase_matches(a: Article, params: SearchParams) -> bool:
    """Does the record satisfy the keyword under the chosen match mode?"""
    kw = keyword_phrase(params)
    if not kw:
        return True
    hay = _hay(a)
    m = mode(params)
    words = keyword_words(params)
    if m == "exact" or len(words) < 2:
        return has_term(hay, kw)
    if m == "all":
        return all(has_term(hay, w) for w in words)
    return any(has_term(hay, w) for w in words)


def enforce(arts: Iterable[Article], params: SearchParams, source_key: str) -> Tuple[List[Article], int]:
    """Drop records that do not contain the keyword (for sources that cannot
    check it themselves). Returns (kept, number dropped)."""
    arts = list(arts)
    if source_key not in ENFORCE_LOCALLY or not keyword_phrase(params):
        return arts, 0
    kept = [a for a in arts if phrase_matches(a, params)]
    return kept, len(arts) - len(kept)


def filter_records(arts: Iterable[Article], params: SearchParams
                   ) -> Tuple[List[Article], List[Tuple[str, int]]]:
    """Apply "Must also contain" and "Exclude terms".

    * Must also contain: the title or abstract must hold at least one of the terms.
    * Exclude: a term in the title or journal name removes the record. A term only
      in the abstract does not remove it; it lowers the score (see :func:`score`).

    Returns (kept, [(rule, rows removed), ...]). A record removed by several
    rules is counted under the first one that applies (musts first, then the
    exclusions in the order typed).
    """
    must = split_terms(params.must_terms)
    excl = split_terms(params.exclude_terms)
    removed: Dict[str, int] = {}
    kept: List[Article] = []
    for a in arts:
        if must and not any(has_term(_hay(a), t) for t in must):
            removed["Must also contain: none of the terms found"] = \
                removed.get("Must also contain: none of the terms found", 0) + 1
            continue
        hit = next((t for t in excl if has_term(a.title, t) or has_term(a.journal, t)), None)
        if hit:
            label = f"Exclude: {hit}"
            removed[label] = removed.get(label, 0) + 1
            continue
        kept.append(a)
    rules = []
    if must:
        rules.append(("Must also contain: none of the terms found",
                      removed.get("Must also contain: none of the terms found", 0)))
    for t in excl:
        rules.append((f"Exclude: {t}", removed.get(f"Exclude: {t}", 0)))
    return kept, rules


# ---------------------------------------------------------------------------
# 4. relevance score
# ---------------------------------------------------------------------------
# Points (maximum 100):
#   phrase (or the Title box) in the title   50   else the share of its words in the title x 30
#   phrase in the abstract                   25   else the share of its words in the abstract x 15
#   "Must also contain" terms found          10 each, up to 20
#   journal / field match                     5
#   exclusion term found only in abstract   -20 each, up to -40
W_TITLE_PHRASE, W_TITLE_WORDS = 50, 30
W_ABS_PHRASE, W_ABS_WORDS = 25, 15
W_MUST_EACH, W_MUST_MAX = 10, 20
W_JOURNAL = 5
W_EXCL_EACH, W_EXCL_MAX = 20, 40
NEUTRAL = 50   # no topic or title was typed, so there is no text to judge


def _targets(params: SearchParams) -> Tuple[str, List[str]]:
    """The phrase and words the score looks for: the topic if there is one,
    otherwise the Title box."""
    kw = keyword_phrase(params)
    if kw:
        return kw, keyword_words(params)
    t = " ".join((params.title or "").split())
    if t:
        from .textutil import words_of
        return t, words_of(t)
    return "", []


def score(a: Article, params: SearchParams) -> int:
    phrase, words = _targets(params)
    must = split_terms(params.must_terms)
    excl = split_terms(params.exclude_terms)
    boosts = split_terms(params.boost_terms)
    if params.journal.strip():
        boosts.append(params.journal.strip())

    pts = 0.0
    if phrase:
        multiword = len(words) > 1
        if has_term(a.title, phrase):
            pts += W_TITLE_PHRASE
        elif words:
            pts += W_TITLE_WORDS * sum(has_term(a.title, w) for w in words) / len(words)
        if has_term(a.abstract, phrase):
            pts += W_ABS_PHRASE
        elif words and a.abstract:
            pts += W_ABS_WORDS * sum(has_term(a.abstract, w) for w in words) / len(words)
        if not multiword and not pts and has_term(_hay(a), phrase):
            pts += W_ABS_PHRASE
    else:
        pts += NEUTRAL

    if must:
        n = sum(has_term(_hay(a), t) for t in must)
        pts += min(W_MUST_MAX, W_MUST_EACH * n)
    if boosts and any(has_term(a.journal, b) for b in boosts):
        pts += W_JOURNAL
    if excl:
        n = sum(has_term(a.abstract, t) for t in excl)
        pts -= min(W_EXCL_MAX, W_EXCL_EACH * n)
    return max(0, min(100, int(round(pts))))


def score_all(arts: Iterable[Article], params: SearchParams) -> None:
    for a in arts:
        a.score = score(a, params)


def sort_best_first(arts: List[Article]) -> List[Article]:
    arts.sort(key=lambda a: (-(a.score if a.score is not None else -1), _neg_date(a.date)))
    return arts


def _neg_date(d: str) -> str:
    """Sort key so that newer dates come first within the same score."""
    digits = re.sub(r"\D", "", d or "")[:8].ljust(8, "0")
    return "".join(str(9 - int(c)) for c in digits)
