# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""Europe PMC search — free, keyless. Biomedical literature plus preprints
(bioRxiv / medRxiv) and some patents and books.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .http_client import get
from .models import Article, SearchParams
from .query import expression
from .textutil import clean

SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def _year(value: str) -> Optional[str]:
    v = value.strip().replace("/", "-")
    return v.split("-")[0] if v and v.split("-")[0].isdigit() else None


def build_query(params: SearchParams) -> str:
    parts: List[str] = []
    kw = expression(params, "(TITLE:{0} OR ABSTRACT:{0})")
    if kw:
        parts.append(kw)
    if params.title.strip():
        parts.append(f'TITLE:"{params.title.strip()}"')
    if params.author.strip():
        parts.append(f'AUTH:"{params.author.strip()}"')
    if params.journal.strip():
        parts.append(f'JOURNAL:"{params.journal.strip()}"')

    y1, y2 = _year(params.date_start), _year(params.date_end)
    if y1 or y2:
        parts.append(f"PUB_YEAR:[{y1 or '1500'} TO {y2 or '3000'}]")

    return " AND ".join(parts) if parts else "*"


def search(
    params: SearchParams, cfg: Optional[Dict[str, str]] = None
) -> Tuple[List[Article], int]:
    q = {
        "query": build_query(params),
        "format": "json",
        "resultType": "core",
        "pageSize": str(max(1, min(params.max_results, 200))),
    }
    if not (params.keyword.strip() or params.title.strip()):
        q["sort"] = "P_PDATE_D desc"        # otherwise Europe PMC's own relevance order
    resp = get(SEARCH, params=q)
    try:
        data = resp.json()
        items = data.get("resultList", {}).get("result", [])
        total = int(data.get("hitCount", 0))
    except (ValueError, KeyError) as exc:
        raise ValueError(f"Unexpected response from Europe PMC: {exc}") from exc

    return [_parse(r) for r in items], total


def _parse(r: Dict) -> Article:
    art = Article(source="Europe PMC")
    art.title = (r.get("title") or "").strip().rstrip(".")

    authors: List[str] = []
    alist = (r.get("authorList") or {}).get("author") or []
    for a in alist:
        name = a.get("fullName") or a.get("collectiveName") or ""
        if name:
            authors.append(name.strip())
    if not authors and r.get("authorString"):
        authors = [x.strip() for x in r["authorString"].rstrip(".").split(",") if x.strip()]
    art.authors = authors

    jinfo = r.get("journalInfo") or {}
    art.journal = ((jinfo.get("journal") or {}).get("title") or r.get("journalTitle") or "").strip()

    art.date = (r.get("firstPublicationDate") or str(r.get("pubYear") or "")).strip()
    art.doi = (r.get("doi") or "").strip()
    art.abstract = clean(r.get("abstractText"))
    cites = r.get("citedByCount")
    art.citations = int(cites) if isinstance(cites, int) else None
    src_code = r.get("source")
    art.kind = "Preprint" if src_code == "PPR" else ("Patent" if src_code == "PAT" else "Paper")
    for u in (r.get("fullTextUrlList") or {}).get("fullTextUrl", []) or []:
        if (u.get("availabilityCode") == "OA") and u.get("url"):
            art.oa_url = u["url"]
            break
    if not art.oa_url and r.get("pmcid") and r.get("isOpenAccess") == "Y":
        art.oa_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{r['pmcid']}/"

    src, rid = r.get("source"), r.get("id")
    if r.get("doi"):
        art.link = f"https://doi.org/{r['doi']}"
    elif src and rid:
        art.link = f"https://europepmc.org/article/{src}/{rid}"
    elif r.get("pmid"):
        art.link = f"https://pubmed.ncbi.nlm.nih.gov/{r['pmid']}/"
    return art
