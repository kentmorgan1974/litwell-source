# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""Plain data structures shared across the app."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional


MATCH_MODES = {
    "exact": "Exact phrase",
    "all": "All words",
    "any": "Any word",
}


@dataclass
class SearchParams:
    """User-supplied search criteria. Every field is optional and combinable."""

    keyword: str = ""
    author: str = ""
    title: str = ""
    journal: str = ""
    date_start: str = ""  # "YYYY", "YYYY-MM", or "YYYY-MM-DD"
    date_end: str = ""
    source: str = "pubmed"  # "pubmed" or "crossref"
    max_results: int = 100
    match_mode: str = "exact"     # "exact" phrase, "all" words, or "any" word
    must_terms: str = ""          # "Must also contain": at least one of these (comma-separated)
    exclude_terms: str = ""       # "Exclude terms": comma-separated
    min_score: int = 0            # drop rows scoring below this (0 = keep everything)
    profile_name: str = ""        # the saved profile in use (for the log only)
    profile_description: str = "" # plain-language description for the optional AI triage
    boost_terms: str = ""         # journal / field names that add a little to the score

    def is_empty(self) -> bool:
        return not any(
            v.strip()
            for v in (
                self.keyword,
                self.author,
                self.title,
                self.journal,
                self.date_start,
                self.date_end,
            )
        )

    def as_log_dict(self) -> dict:
        d = asdict(self)
        d.pop("max_results", None)
        return d

    def mode_label(self) -> str:
        return MATCH_MODES.get(self.match_mode, MATCH_MODES["exact"])

    def summary(self) -> str:
        """Human-readable one-line description of the search fields used.

        Example: 'Keyword: J2 antibody; Journal: Nature; Date: 2023 to 2024'
        """
        parts: list[str] = []
        if self.keyword.strip():
            kw = f"Keyword: {self.keyword.strip()}"
            if self.match_mode in ("all", "any"):
                kw += f" ({self.mode_label().lower()})"
            parts.append(kw)
        if self.author.strip():
            parts.append(f"Author: {self.author.strip()}")
        if self.title.strip():
            parts.append(f"Title: {self.title.strip()}")
        if self.journal.strip():
            parts.append(f"Journal: {self.journal.strip()}")
        if self.must_terms.strip():
            parts.append(f"Must also contain: {self.must_terms.strip()}")
        if self.exclude_terms.strip():
            parts.append(f"Exclude: {self.exclude_terms.strip()}")
        ds, de = self.date_start.strip(), self.date_end.strip()
        if ds and de:
            parts.append(f"Date: {ds} to {de}")
        elif ds:
            parts.append(f"Date: from {ds}")
        elif de:
            parts.append(f"Date: until {de}")
        return "; ".join(parts)


def make_dedupe_key(title: str, doi: str) -> Optional[str]:
    """The key used to decide whether two records are the same paper.

    DOI (case-insensitive) when available, otherwise a whitespace-normalized
    lower-cased title. Kept in one place so append-time dedupe and the
    'remove duplicates' tool always agree.
    """
    if doi and doi.strip():
        return doi.strip().lower()
    if title and title.strip():
        return "title::" + " ".join(title.lower().split())
    return None


@dataclass
class Article:
    """One normalized literature record, regardless of source."""

    title: str = ""
    authors: List[str] = field(default_factory=list)
    journal: str = ""
    date: str = ""
    doi: str = ""
    link: str = ""
    source: str = ""
    abstract: str = ""
    oa_url: str = ""              # a free full-text link, when one is known
    citations: Optional[int] = None
    kind: str = ""                # "Paper", "Preprint" or "Patent"
    sources: List[str] = field(default_factory=list)   # every source key that returned it
    score: Optional[int] = None   # relevance score, 0-100
    ai_rating: str = ""           # "Relevant" / "Maybe" / "Not relevant" (optional AI triage)
    ai_reason: str = ""
    search_date: str = ""         # when the run that first found it happened
    search_terms: str = ""
    is_new: Optional[bool] = None # True/False when a previous run existed, else None

    @property
    def authors_str(self) -> str:
        return "; ".join(a for a in self.authors if a)

    def dedupe_key(self) -> Optional[str]:
        """Key used to skip duplicates. DOI when present, else normalized title."""
        return make_dedupe_key(self.title, self.doi)


@dataclass
class SearchOutcome:
    """Result of one source's part of a run, handed back to the UI."""

    params: SearchParams
    articles: List[Article] = field(default_factory=list)
    total_found: int = 0          # total matches reported by the API
    fetched: int = 0              # records actually retrieved
    removed: int = 0              # of those, removed by the match / filter rules
    added: int = 0                # new rows written to the output file
    skipped_duplicates: int = 0   # kept, but already in the file or found by another source
    error: str = ""
    skipped: bool = False         # not attempted (no API key)

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def status(self) -> str:
        if self.skipped:
            return "Skipped: no key"
        return "OK" if self.ok else "Error: " + self.error.splitlines()[0][:200]


@dataclass
class SourceResult:
    """One source's part of a multi-source search."""

    key: str
    name: str
    outcome: SearchOutcome


@dataclass
class MultiOutcome:
    """Result of searching several sources at once, handed back to the UI."""

    params: SearchParams
    results: List[SourceResult] = field(default_factory=list)
    error: str = ""               # set only when nothing could be attempted
    rules: List[tuple] = field(default_factory=list)   # (filter rule, rows removed)
    merged_copies: int = 0        # copies of one paper folded together
    kept: int = 0                 # records that passed every filter
    new_rows: int = 0             # of those, new to the output file
    known_rows: int = 0           # of those, already in the file
    total_rows: int = 0           # rows in the file afterwards
    notes: List[str] = field(default_factory=list)     # warnings and one-line notes
    ai_model: str = ""          # the local model AI triage used, if it ran

    @property
    def succeeded(self) -> List[SourceResult]:
        return [r for r in self.results if r.outcome.ok]

    @property
    def failed(self) -> List[SourceResult]:
        return [r for r in self.results if not r.outcome.ok]

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.succeeded)

    @property
    def added(self) -> int:
        return self.new_rows

    @property
    def skipped_duplicates(self) -> int:
        return self.known_rows

    @property
    def removed(self) -> int:
        return sum(n for _rule, n in self.rules)
