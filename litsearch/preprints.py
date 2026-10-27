# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""Preprint servers — one combined search across the open preprint ecosystem.

The COAR "Directory of Open Access Preprint Repositories" (DOAPR) lists ~90
independent servers and has no single search API. The practical way to search
them together is through the aggregators that harvest them, so this source fans
one query out to three free, keyless backends and merges the results:

  * OSF Preprints API   - every OSF-hosted server (OSF Preprints, SocArXiv,
                          PsyArXiv, EarthArXiv, engrXiv, MarXiv, MetaArXiv,
                          EdArXiv, AfricArXiv, AgriXiv, LawArXiv, SportRxiv ...)
  * Europe PMC (SRC:PPR) - bioRxiv, medRxiv, Research Square, Preprints.org,
                          SSRN (biomedical), ChemRxiv, Authorea, JMIR, ARPHA,
                          SciELO Preprints, Qeios, PeerJ Preprints ...
  * OpenAlex (type:preprint) - arXiv, SSRN, ChemRxiv, TechRxiv, ESSOAr, HAL,
                          Zenodo, Figshare, MPRA, viXra, CERN ... (anything
                          OpenAlex harvests from Crossref / DataCite / OAI-PMH)

A failure in one backend never sinks the search: the others still return and
the problem is reported through ``say``.

The **Journal** box doubles as a *server filter* here — type a server name
(e.g. "bioRxiv", "SocArXiv", "SSRN") to restrict results to it.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Tuple

from . import europepmc, openalex
from .http_client import NetworkError, get
from .models import Article, SearchParams, make_dedupe_key
from .query import expression, keyword_phrase, keyword_words, mode
from .textutil import clean, has_term

OSF_PREPRINTS = "https://api.osf.io/v2/preprints/"
OSF_PROVIDERS = "https://api.osf.io/v2/preprint_providers/"
EPMC_SEARCH = europepmc.SEARCH
OA_WORKS = openalex.WORKS
OA_SOURCES = "https://api.openalex.org/sources"

Say = Callable[[str], None]

_osf_providers: Optional[Dict[str, str]] = None  # id -> display name


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _short(server: str) -> str:
    """'bioRxiv (Cold Spring Harbor Laboratory)' -> 'bioRxiv'."""
    return re.sub(r"\s*\(.*\)\s*$", "", server or "").strip() or server


# --------------------------------------------------------------------------
# OSF
# --------------------------------------------------------------------------
def _providers() -> Dict[str, str]:
    global _osf_providers
    if _osf_providers is None:
        resp = get(OSF_PROVIDERS, params={"page[size]": "100"})
        _osf_providers = {
            p["id"]: p["attributes"]["name"] for p in resp.json().get("data", [])
        }
    return _osf_providers


def _match_provider(name: str) -> Optional[str]:
    n = _norm(name)
    if not n:
        return None
    for pid, pname in _providers().items():
        if n in (_norm(pid), _norm(pname)):
            return pid
    for pid, pname in _providers().items():
        if n in _norm(pname) or _norm(pname) in n:
            return pid
    return None


def _name_hit(query: str, names: List[str]) -> bool:
    toks = [t for t in re.split(r"[\s,.]+", query.lower()) if t]
    return any(all(t in nm.lower() for t in toks) for nm in names)


def _osf(params: SearchParams, limit: int, say: Say) -> Tuple[List[Article], int]:
    has_text = bool(params.keyword.strip() or params.title.strip())
    if not has_text and params.author.strip():
        say("OSF has no author-only search — skipped (other servers still searched).")
        return [], 0

    base: Dict[str, str] = {
        # Author names need an embed, which makes big pages slow — keep pages
        # small and request only the fields we use.
        "page[size]": str(max(1, min(limit, 20))),
        "embed": "bibliographic_contributors",
        "fields[preprints]": "title,date_created,date_published,"
                             "original_publication_date,doi,provider,"
                             "bibliographic_contributors",
        "fields[contributors]": "users",
        "fields[users]": "full_name",
        "sort": "-date_created",
    }
    if params.journal.strip():
        pid = _match_provider(params.journal)
        if not pid:
            return [], 0  # the named server isn't an OSF-hosted one
        base["filter[provider]"] = pid
    lo, hi = openalex._iso(params.date_start, end=False), openalex._iso(params.date_end, end=True)
    if lo:
        base["filter[date_created][gte]"] = lo
    if hi:
        base["filter[date_created][lte]"] = hi

    # OSF filters are single-field substring matches, so run title and abstract
    # separately and merge.
    queries: List[Dict[str, str]] = []
    if params.title.strip():
        queries.append({**base, "filter[title]": params.title.strip()})
    if params.keyword.strip():
        # An exact phrase is one substring; "all" / "any" run one query per word
        # (the all-words rule is then enforced on the results below).
        needles = [keyword_phrase(params)] if mode(params) == "exact" else keyword_words(params)
        for needle in needles:
            queries.append({**base, "filter[title]": needle})
            queries.append({**base, "filter[description]": needle})
    if not queries:  # date/server-only search
        queries.append(base)

    seen: Dict[str, Article] = {}
    total = 0
    for q in queries:
        data = get(OSF_PREPRINTS, params=q, max_retries=1, timeout=25).json()
        total += int(data.get("links", {}).get("meta", {}).get("total", 0) or 0)
        for item in data.get("data", []):
            art = _osf_parse(item)
            if params.author.strip() and not _name_hit(params.author, art.authors):
                continue
            if mode(params) == "all" and params.keyword.strip():
                hay = art.title + " " + art.abstract
                if not all(has_term(hay, w) for w in keyword_words(params)):
                    continue
            seen.setdefault(item["id"], art)
    arts = list(seen.values())
    return arts[:limit], total


def _osf_parse(item: Dict) -> Article:
    a = item.get("attributes", {})
    links = item.get("links", {})
    art = Article()
    art.title = (a.get("title") or "").strip()

    names: List[str] = []
    contribs = (item.get("embeds", {}).get("bibliographic_contributors") or {}).get("data", [])
    for c in contribs:
        u = (c.get("embeds", {}).get("users") or {}).get("data", {})
        nm = (u.get("attributes", {}) or {}).get("full_name")
        if nm:
            names.append(nm.strip())
    art.authors = names

    pid = (item.get("relationships", {}).get("provider", {}).get("data") or {}).get("id", "")
    server = _short(_providers().get(pid, pid) if pid else "OSF")
    art.journal = server
    art.source = f"Preprint — {server}"
    art.kind = "Preprint"
    art.abstract = clean(a.get("description"))

    art.date = (a.get("original_publication_date") or a.get("date_published") or a.get("date_created") or "")[:10]
    pre = links.get("preprint_doi", "") or ""
    art.doi = pre.replace("https://doi.org/", "") or (a.get("doi") or "")
    art.link = links.get("html") or (f"https://doi.org/{art.doi}" if art.doi else "")
    return art


# --------------------------------------------------------------------------
# Europe PMC (preprint index)
# --------------------------------------------------------------------------
def _epmc_query(params: SearchParams) -> str:
    parts: List[str] = ["SRC:PPR"]
    kw = expression(params, "(TITLE:{0} OR ABSTRACT:{0})")
    if kw:
        parts.append(kw)
    if params.title.strip():
        parts.append(f'TITLE:"{params.title.strip()}"')
    if params.author.strip():
        parts.append(f'AUTH:"{params.author.strip()}"')
    if params.journal.strip():
        parts.append(f'PUBLISHER:"{params.journal.strip()}"')
    lo = openalex._iso(params.date_start, end=False)
    hi = openalex._iso(params.date_end, end=True)
    if lo or hi:
        parts.append(f"FIRST_PDATE:[{lo or '1900-01-01'} TO {hi or '2999-12-31'}]")
    return " AND ".join(parts)


def _epmc(params: SearchParams, limit: int, say: Say) -> Tuple[List[Article], int]:
    resp = get(
        EPMC_SEARCH,
        params={
            "query": _epmc_query(params),
            "format": "json",
            "resultType": "core",
            "pageSize": str(max(1, min(limit, 200))),
            **({} if params.keyword.strip() else {"sort": "P_PDATE_D desc"}),
        },
    )
    data = resp.json()
    out: List[Article] = []
    for r in data.get("resultList", {}).get("result", []):
        art = europepmc._parse(r)
        server = ((r.get("bookOrReportDetails") or {}).get("publisher") or "").strip()
        server = _short(server)
        if server:
            art.journal = server
        art.source = f"Preprint — {server or 'Europe PMC'}"
        art.kind = "Preprint"
        out.append(art)
    return out, int(data.get("hitCount", 0))


# --------------------------------------------------------------------------
# OpenAlex (type:preprint)
# --------------------------------------------------------------------------
def _oa_source_id(name: str, cfg=None) -> Optional[str]:
    return openalex.source_id(name, cfg)


def _oa(params: SearchParams, limit: int, say: Say, cfg) -> Tuple[List[Article], int]:
    filters: List[str] = ["type:preprint"]
    kw = expression(params, "{}").replace(",", " ")
    if kw:
        filters.append("title_and_abstract.search:" + kw)
    if params.title.strip():
        filters.append("title.search:" + params.title.strip())
    if params.author.strip():
        filters.append("raw_author_name.search:" + params.author.strip())
    if params.journal.strip():
        sid = _oa_source_id(params.journal, cfg)
        if not sid:
            return [], 0
        filters.append(f"primary_location.source.id:{sid}")
    lo = openalex._iso(params.date_start, end=False)
    hi = openalex._iso(params.date_end, end=True)
    if lo:
        filters.append(f"from_publication_date:{lo}")
    if hi:
        filters.append(f"to_publication_date:{hi}")

    q = {
        "filter": ",".join(filters),
        "per_page": str(max(1, min(limit, 200))),
        "sort": "relevance_score:desc" if kw else "publication_date:desc",
    }
    openalex.add_auth(q, cfg)
    data = get(OA_WORKS, params=q).json()
    out: List[Article] = []
    for w in data.get("results", []):
        art = openalex._parse(w)
        art.journal = _short(art.journal)
        art.source = f"Preprint — {art.journal or 'OpenAlex'}"
        art.kind = "Preprint"
        out.append(art)
    return out, int(data.get("meta", {}).get("count", 0))


# --------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------
def search(
    params: SearchParams, cfg: Optional[Dict[str, str]] = None, say: Optional[Say] = None
) -> Tuple[List[Article], int]:
    say = say or (lambda _m: None)
    want = max(1, params.max_results)

    backends = [
        ("OSF (SocArXiv, PsyArXiv, EarthArXiv, engrXiv…)", lambda: _osf(params, want, say)),
        ("Europe PMC (bioRxiv, medRxiv, Research Square…)", lambda: _epmc(params, want, say)),
        ("OpenAlex (arXiv, SSRN, ChemRxiv, TechRxiv…)", lambda: _oa(params, want, say, cfg)),
    ]

    lists: List[List[Article]] = []
    total = 0
    errors: List[str] = []
    for label, fn in backends:
        short = label.split(" (")[0]
        say(f"  · {label}")
        try:
            arts, tot = fn()
        except (NetworkError, ValueError, KeyError) as exc:
            errors.append(f"{short}: {exc}")
            say(f"    ! {short} failed — {exc}")
            continue
        total += tot
        say(f"    {len(arts)} record(s)")
        lists.append(arts)

    if not any(lists) and errors:
        raise NetworkError("All preprint backends failed — " + " | ".join(errors))

    # Round-robin across backends so no single server dominates, skipping
    # duplicates (same DOI / title) and filling the whole budget.
    merged: List[Article] = []
    seen = set()
    for i in range(max((len(l) for l in lists), default=0)):
        for l in lists:
            if i < len(l) and len(merged) < want:
                a = l[i]
                k = make_dedupe_key(a.title, a.doi) or f"row::{id(a)}"
                if k not in seen:
                    seen.add(k)
                    merged.append(a)

    if not params.keyword.strip():
        merged.sort(key=lambda a: a.date or "", reverse=True)
    return merged, total
