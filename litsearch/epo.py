# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""Worldwide patent search via the EPO Open Patent Services (OPS) API.

This is Espacenet's data — roughly 100 patent authorities (US, EP, WO, CN, JP,
KR, DE, GB, FR ...). It is **free** but needs OAuth credentials:

    1. Register at https://developers.epo.org  (free)
    2. Create an app -> you get a "Consumer Key" and "Consumer Secret"
    3. Put both in the app: File -> API Keys & Contact

Free tier allows ~4 GB of downloaded data per week.

Returns published patent documents from ~100 countries — both applications
(kind code A*) and granted patents (kind code B*). Applications are tagged
"(application)" in the Date column, like the USPTO source.

Field mapping into the shared columns:
    Title    -> invention title (English where available)
    Authors  -> inventors
    Journal  -> applicant(s) / owner
    Date     -> publication date  (+ "(application)" for A-kind documents)
    Link     -> Google Patents page for the publication number
    DOI      -> publication number, e.g. "EP1000000A1" (drives dedup)
"""

from __future__ import annotations

import base64
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

from .http_client import NetworkError, get, post
from .models import Article, SearchParams
from .query import keyword_phrase, keyword_words, mode
from .textutil import clean
from .patlinks import patent_url

AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search/biblio"
REGISTER_URL = "https://developers.epo.org"

_NS = {
    "ops": "http://ops.epo.org",
    "ex": "http://www.epo.org/exchange",
}

# Cached bearer token: (token_string, expiry_epoch_seconds)
_token: Optional[Tuple[str, float]] = None


def _get_token(key: str, secret: str) -> str:
    global _token
    if _token and _token[1] - time.time() > 30:
        return _token[0]

    basic = base64.b64encode(f"{key}:{secret}".encode("utf-8")).decode("ascii")
    resp = post(
        AUTH_URL,
        data={"grant_type": "client_credentials"},
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        payload = resp.json()
        token = payload["access_token"]
        ttl = float(payload.get("expires_in", 1200))
    except (ValueError, KeyError) as exc:
        raise NetworkError(f"EPO OPS did not return an access token: {exc}") from exc

    _token = (token, time.time() + ttl)
    return token


def _cql_value(v: str) -> str:
    v = v.strip().replace('"', "")
    return f'"{v}"' if " " in v else v


def _yyyymmdd(value: str, *, end: bool) -> Optional[str]:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 4:
        return None
    year = digits[:4]
    if len(digits) >= 8:
        return digits[:8]
    return f"{year}1231" if end else f"{year}0101"


def _cql_keyword(params: SearchParams) -> str:
    """Keyword as CQL over title and abstract. 'all' / 'any' use CQL's own
    word-list relations."""
    phrase = keyword_phrase(params).replace('"', "")
    if not phrase:
        return ""
    m = mode(params)
    if m == "exact" or len(keyword_words(params)) < 2:
        return f'(ti="{phrase}" or ab="{phrase}")'
    words = " ".join(keyword_words(params))
    rel = "all" if m == "all" else "any"
    return f'(ti {rel} "{words}" or ab {rel} "{words}")'


def build_cql(params: SearchParams) -> str:
    parts: List[str] = []
    kw = _cql_keyword(params)
    if kw:
        parts.append(kw)
    if params.title.strip():
        parts.append(f"ti={_cql_value(params.title)}")
    if params.author.strip():
        parts.append(f"in={_cql_value(params.author)}")
    if params.journal.strip():
        parts.append(f"pa={_cql_value(params.journal)}")

    lo = _yyyymmdd(params.date_start, end=False)
    hi = _yyyymmdd(params.date_end, end=True)
    if lo or hi:
        parts.append(f'pd within "{lo or "19000101"} {hi or "29991231"}"')

    return " and ".join(parts) if parts else "txt=*"


def search(
    params: SearchParams, cfg: Optional[Dict[str, str]] = None
) -> Tuple[List[Article], int]:
    cfg = cfg or {}
    key = cfg.get("epo_ops_key", "").strip()
    secret = cfg.get("epo_ops_secret", "").strip()
    if not (key and secret):
        raise ValueError(
            "Worldwide patent search needs free EPO OPS credentials.\n"
            f"Register at {REGISTER_URL}, create an app to get a Consumer Key "
            "and Consumer Secret, then paste both into File -> API Keys & Contact."
        )

    token = _get_token(key, secret)
    # OPS returns at most 100 results per request.
    end = max(1, min(params.max_results, 100))
    resp = get(
        SEARCH_URL,
        params={"q": build_cql(params), "Range": f"1-{end}"},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/xml"},
    )
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        raise ValueError(f"Could not parse EPO OPS response: {exc}") from exc

    search_node = root.find(".//ops:biblio-search", _NS)
    total = 0
    if search_node is not None:
        try:
            total = int(search_node.get("total-result-count", "0"))
        except ValueError:
            total = 0

    # Keep OPS's own relevance order — sorting by date just surfaces whichever
    # country published most yesterday (usually the US), drowning out the
    # worldwide coverage that is the whole point of this source.
    articles = [
        _parse(doc) for doc in root.findall(".//ex:exchange-document", _NS)
    ]
    return articles, total


def _first_text(node: ET.Element, path: str) -> str:
    found = node.find(path, _NS)
    return "".join(found.itertext()).strip() if found is not None else ""


def _parse(doc: ET.Element) -> Article:
    art = Article(source="EPO / Worldwide Patents")

    titles = doc.findall(".//ex:invention-title", _NS)
    art.title = ""
    for t in titles:
        if t.get("lang") == "en":
            art.title = "".join(t.itertext()).strip()
            break
    if not art.title and titles:
        art.title = "".join(titles[0].itertext()).strip()

    inventors: List[str] = []
    for name in doc.findall(
        ".//ex:inventors/ex:inventor[@data-format='original']/ex:inventor-name/ex:name",
        _NS,
    ):
        txt = "".join(name.itertext()).strip().rstrip(",")
        if txt and txt not in inventors:
            inventors.append(txt)
    art.authors = inventors

    applicants: List[str] = []
    for name in doc.findall(
        ".//ex:applicants/ex:applicant[@data-format='original']/ex:applicant-name/ex:name",
        _NS,
    ):
        txt = "".join(name.itertext()).strip().rstrip(",")
        if txt and txt not in applicants:
            applicants.append(txt)
    art.journal = "; ".join(applicants)

    pub = doc.find(
        ".//ex:publication-reference/ex:document-id[@document-id-type='docdb']", _NS
    )
    country = doc_num = kind = date = ""
    if pub is not None:
        country = _first_text(pub, "ex:country")
        doc_num = _first_text(pub, "ex:doc-number")
        kind = _first_text(pub, "ex:kind")
        date = _first_text(pub, "ex:date")
    abs_nodes = doc.findall(".//ex:abstract[@lang='en']/ex:p", _NS) or doc.findall(".//ex:abstract/ex:p", _NS)
    art.abstract = clean(" ".join("".join(p.itertext()) for p in abs_nodes))
    art.kind = "Patent"
    iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 else date
    # EPO kind codes: A* = published application (still pending), B* = granted.
    is_app = kind.startswith("A")
    art.date = f"{iso} (application)" if is_app else iso

    number = f"{country}{doc_num}{kind}"
    art.doi = number
    if country and doc_num:
        art.link = patent_url(number, date_iso=iso, is_application=is_app)
    return art
