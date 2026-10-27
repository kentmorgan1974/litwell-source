# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""OpenAlex works search — free, keyless, covers all disciplines.

Supplying a contact email (config: ``ncbi_email`` is reused) uses OpenAlex's
faster "polite pool".
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .http_client import get
from .models import Article, SearchParams
from .query import expression, keyword_phrase
from .textutil import clean

WORKS = "https://api.openalex.org/works"
SOURCES_URL = "https://api.openalex.org/sources"


def add_auth(q: Dict[str, str], cfg: Optional[Dict[str, str]]) -> None:
    """Attach the optional free API key (own daily budget) and contact email."""
    if cfg and cfg.get("openalex_api_key"):
        q["api_key"] = cfg["openalex_api_key"].strip()
    email = ((cfg or {}).get("contact_email") or (cfg or {}).get("ncbi_email") or "").strip()
    if email:
        q["mailto"] = email


def source_id(name: str, cfg=None) -> Optional[str]:
    """OpenAlex id of the journal / server called ``name`` (None if not found)."""
    q = {"search": name, "per_page": "3", "select": "id,display_name"}
    add_auth(q, cfg)
    try:
        data = get(SOURCES_URL, params=q).json()
    except Exception:
        return None
    want = "".join(ch for ch in name.lower() if ch.isalnum())
    for s in data.get("results", []):
        have = "".join(ch for ch in s.get("display_name", "").lower() if ch.isalnum())
        if want and want in have:
            return s["id"].rsplit("/", 1)[-1]
    return None


def _abstract(w: Dict) -> str:
    """OpenAlex stores abstracts as {word: [positions]}; put them back in order."""
    inv = w.get("abstract_inverted_index") or {}
    slots: Dict[int, str] = {}
    for word, positions in inv.items():
        for p in positions or []:
            slots[p] = word
    return clean(" ".join(slots[i] for i in sorted(slots)))


def _iso(value: str, *, end: bool) -> Optional[str]:
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
    filters: List[str] = []

    kw = expression(params, "{}").replace(",", " ")
    if kw:
        filters.append("title_and_abstract.search:" + kw)
    if params.journal.strip():
        sid = source_id(params.journal, cfg)
        if sid:
            filters.append(f"primary_location.source.id:{sid}")
        else:
            filters.append("default.search:" + params.journal.strip().replace(",", " "))
    if params.title.strip():
        filters.append("title.search:" + params.title.strip())
    if params.author.strip():
        filters.append("raw_author_name.search:" + params.author.strip())

    start = _iso(params.date_start, end=False)
    end = _iso(params.date_end, end=True)
    if start:
        filters.append(f"from_publication_date:{start}")
    if end:
        filters.append(f"to_publication_date:{end}")

    if not filters:
        raise ValueError("OpenAlex needs at least one search field.")

    q: Dict[str, str] = {
        "filter": ",".join(filters),
        "per_page": str(max(1, min(params.max_results, 200))),
        "sort": "relevance_score:desc" if kw else "publication_date:desc",
    }
    add_auth(q, cfg)

    resp = get(WORKS, params=q)
    try:
        data = resp.json()
        items = data["results"]
        total = int(data["meta"]["count"])
    except (ValueError, KeyError) as exc:
        raise ValueError(f"Unexpected response from OpenAlex: {exc}") from exc

    return [_parse(w) for w in items], total


def _parse(w: Dict) -> Article:
    art = Article(source="OpenAlex")
    art.title = (w.get("title") or w.get("display_name") or "").strip()
    art.authors = [
        (a.get("author") or {}).get("display_name", "").strip()
        for a in w.get("authorships", [])
        if (a.get("author") or {}).get("display_name")
    ]

    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    art.journal = (src.get("display_name") or "").strip()

    art.date = (w.get("publication_date") or str(w.get("publication_year") or "")).strip()

    doi = w.get("doi") or ""
    art.doi = doi.replace("https://doi.org/", "").strip()

    art.abstract = _abstract(w)
    art.oa_url = ((w.get("open_access") or {}).get("oa_url") or "").strip()
    cites = w.get("cited_by_count")
    art.citations = int(cites) if isinstance(cites, int) else None
    art.kind = "Preprint" if w.get("type") == "preprint" else "Paper"
    art.link = (
        loc.get("landing_page_url")
        or (doi if doi else "")
        or w.get("id", "")
    )
    return art
