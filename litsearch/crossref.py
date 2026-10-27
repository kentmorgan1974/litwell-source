# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""Crossref works search — secondary source for non-biomedical topics.

Crossref is free and keyless. Supplying a contact email (config: ``ncbi_email``
is reused) puts requests in Crossref's faster "polite" pool.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .http_client import get
from .models import Article, SearchParams
from .textutil import clean

WORKS = "https://api.crossref.org/works"


def _fill_date(value: str, *, end: bool) -> Optional[str]:
    """Normalize 'YYYY' / 'YYYY-MM' / 'YYYY-MM-DD' to a full ISO date."""
    v = value.strip().replace("/", "-")
    if not v:
        return None
    bits = v.split("-")
    try:
        y = int(bits[0])
    except ValueError:
        return None
    m = int(bits[1]) if len(bits) > 1 and bits[1] else (12 if end else 1)
    d = int(bits[2]) if len(bits) > 2 and bits[2] else (28 if end else 1)
    return f"{y:04d}-{m:02d}-{d:02d}"


def search(
    params: SearchParams, cfg: Optional[Dict[str, str]] = None
) -> Tuple[List[Article], int]:
    q: Dict[str, str] = {
        "rows": str(max(1, min(params.max_results, 200))),
        "select": "title,author,container-title,issued,published,DOI,URL,abstract,is-referenced-by-count,type",
    }
    if params.keyword.strip():
        # Crossref has no phrase operator: it ranks by similarity. The exact-phrase
        # rule is enforced afterwards, on the title and abstract (see search.py).
        q["query.bibliographic"] = " ".join(params.keyword.split())
    if params.title.strip():
        q["query.title"] = params.title.strip()
    if params.author.strip():
        q["query.author"] = params.author.strip()
    if params.journal.strip():
        q["query.container-title"] = params.journal.strip()

    filters: List[str] = []
    start = _fill_date(params.date_start, end=False)
    end = _fill_date(params.date_end, end=True)
    if start:
        filters.append(f"from-pub-date:{start}")
    if end:
        filters.append(f"until-pub-date:{end}")
    if filters:
        q["filter"] = ",".join(filters)

    if not any(k.startswith("query") for k in q):
        q["query"] = "*"

    email = ((cfg or {}).get("contact_email") or (cfg or {}).get("ncbi_email") or "").strip()
    if email:
        q["mailto"] = email

    resp = get(WORKS, params=q)
    try:
        msg = resp.json()["message"]
        items = msg.get("items", [])
        total = int(msg.get("total-results", 0))
    except (ValueError, KeyError) as exc:
        raise ValueError(f"Unexpected response from Crossref: {exc}") from exc

    return [_parse_item(it) for it in items], total


def _parse_item(it: Dict) -> Article:
    art = Article(source="Crossref")
    titles = it.get("title") or []
    art.title = titles[0].strip() if titles else ""

    authors: List[str] = []
    for a in it.get("author", []) or []:
        if a.get("name"):
            authors.append(a["name"].strip())
            continue
        family = (a.get("family") or "").strip()
        given = (a.get("given") or "").strip()
        if family:
            authors.append(f"{family}, {given}".rstrip(", "))
    art.authors = authors

    containers = it.get("container-title") or []
    art.journal = containers[0].strip() if containers else ""

    art.date = _parse_date(it.get("issued") or it.get("published"))
    art.doi = (it.get("DOI") or "").strip()
    art.abstract = clean(it.get("abstract"))
    n = it.get("is-referenced-by-count")
    art.citations = int(n) if isinstance(n, int) else None
    art.kind = "Preprint" if it.get("type") == "posted-content" else "Paper"
    art.link = (it.get("URL") or "").strip() or (
        f"https://doi.org/{art.doi}" if art.doi else ""
    )
    return art


def _parse_date(node: Optional[Dict]) -> str:
    if not node:
        return ""
    dp = node.get("date-parts") or [[]]
    parts = dp[0] if dp else []
    # Crossref sometimes sends [[null]] (no date) or a null month/day: keep only the
    # leading parts that are real numbers.
    good = []
    for x in parts or []:
        try:
            good.append(int(x))
        except (TypeError, ValueError):
            break
    if not good:
        return ""
    return "-".join(f"{v:02d}" if i else str(v) for i, v in enumerate(good))
