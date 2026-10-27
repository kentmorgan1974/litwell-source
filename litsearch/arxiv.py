# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""arXiv search — free, keyless. Preprints in physics, mathematics, computer
science, quantitative biology, economics and statistics.

The arXiv API returns Atom XML and requires HTTPS plus a descriptive
User-Agent (handled by http_client).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

from .http_client import get
from .models import Article, SearchParams
from .query import expression
from .textutil import clean

API = "https://export.arxiv.org/api/query"

_NS = {
    "a": "http://www.w3.org/2005/Atom",
    "x": "http://arxiv.org/schemas/atom",
    "o": "http://a9.com/-/spec/opensearch/1.1/",
}


def _date_bound(value: str, *, end: bool) -> Optional[str]:
    v = "".join(ch for ch in value if ch.isdigit())
    if len(v) < 4:
        return None
    year = v[:4]
    if end:
        mmdd = (v[4:8] + "1231")[:4]
        return f"{year}{mmdd}2359"
    mmdd = (v[4:8] + "0101")[:4]
    return f"{year}{mmdd}0000"


def build_query(params: SearchParams) -> str:
    parts: List[str] = []
    kw = expression(params, "(ti:{0} OR abs:{0})")
    if kw:
        parts.append(kw)
    if params.title.strip():
        parts.append(f'ti:"{params.title.strip()}"')
    if params.author.strip():
        parts.append(f'au:"{params.author.strip()}"')
    if params.journal.strip():
        parts.append(f'jr:"{params.journal.strip()}"')

    lo = _date_bound(params.date_start, end=False)
    hi = _date_bound(params.date_end, end=True)
    if lo or hi:
        parts.append(
            f"submittedDate:[{lo or '190001010000'} TO {hi or '299912312359'}]"
        )

    return " AND ".join(parts) if parts else "all:*"


def search(
    params: SearchParams, cfg: Optional[Dict[str, str]] = None
) -> Tuple[List[Article], int]:
    q = {
        "search_query": build_query(params),
        "start": "0",
        "max_results": str(max(1, min(params.max_results, 200))),
        "sortBy": "relevance" if (params.keyword.strip() or params.title.strip()) else "submittedDate",
        "sortOrder": "descending",
    }
    resp = get(API, params=q)
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        raise ValueError(f"Could not parse arXiv response: {exc}") from exc

    total_text = root.findtext("o:totalResults", default="0", namespaces=_NS)
    try:
        total = int(total_text)
    except ValueError:
        total = 0

    articles = [_parse(e) for e in root.findall("a:entry", _NS)]
    return articles, total


def _parse(e: ET.Element) -> Article:
    art = Article(source="arXiv")
    art.title = " ".join((e.findtext("a:title", default="", namespaces=_NS)).split())
    art.authors = [
        (a.findtext("a:name", default="", namespaces=_NS)).strip()
        for a in e.findall("a:author", _NS)
        if a.findtext("a:name", namespaces=_NS)
    ]
    art.journal = (
        e.findtext("x:journal_ref", default="", namespaces=_NS) or "arXiv preprint"
    ).strip()
    art.date = (e.findtext("a:published", default="", namespaces=_NS))[:10]
    art.doi = (e.findtext("x:doi", default="", namespaces=_NS) or "").strip()

    art.abstract = clean(e.findtext("a:summary", default="", namespaces=_NS))
    art.kind = "Preprint"
    art.link = ""
    for link in e.findall("a:link", _NS):
        if link.get("rel") == "alternate":
            art.link = link.get("href", "")
        elif link.get("title") == "pdf":
            art.oa_url = link.get("href", "")
    if not art.doi and art.link:
        # arXiv papers have a DataCite DOI; using it lets other sources' copies merge.
        m = re.search(r"arxiv\.org/abs/([^v]+?)(?:v\d+)?$", art.link)
        if m:
            art.doi = "10.48550/arXiv." + m.group(1)
    if not art.link:
        art.link = (e.findtext("a:id", default="", namespaces=_NS)).strip()
    return art
