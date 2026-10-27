# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""US patent search via the USPTO Open Data Portal (ODP) API.

PatentsView's standalone API was retired and folded into the USPTO Open Data
Portal. Get a **free** API key:

    1. Sign in / create an account at  https://data.uspto.gov
    2. Open your account settings and generate / copy your API key
    3. Put it in the app:  File -> API Keys & Contact  ("USPTO API key")

Endpoint:  https://api.uspto.gov/api/v1/patent/applications/search
Auth:      request header  X-API-KEY: <your key>

Returns both granted patents and published (still-pending) applications.
Pending ones are tagged "(application)" in the Date column.

Field mapping into the shared columns:
    Title    -> invention title
    Authors  -> inventors
    Journal  -> applicant / owner
    Date     -> grant date, or "<pub date> (application)" if not yet granted
    Link     -> Google Patents page for granted patents (USPTO PDF for the
                first few weeks, and always for pending applications)
    DOI      -> US patent number, or the publication number -> drives dedup
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .http_client import NetworkError, get
from .models import Article, SearchParams
from .query import expression
from .patlinks import patent_url

ENDPOINT = "https://api.uspto.gov/api/v1/patent/applications/search"
KEY_URL = "https://data.uspto.gov"


def _api_key(cfg: Optional[Dict[str, str]]) -> str:
    cfg = cfg or {}
    return (cfg.get("uspto_api_key") or cfg.get("patentsview_api_key") or "").strip()


def _iso(value: str, *, end: bool) -> Optional[str]:
    v = value.strip().replace("/", "-")
    if not v:
        return None
    bits = v.split("-")
    if not bits[0].isdigit():
        return None
    y = int(bits[0])
    m = int(bits[1]) if len(bits) > 1 and bits[1] else (12 if end else 1)
    d = int(bits[2]) if len(bits) > 2 and bits[2] else (28 if end else 1)
    return f"{y:04d}-{m:02d}-{d:02d}"


def _phrase(v: str) -> str:
    v = v.strip().replace('"', "")
    return f'"{v}"' if " " in v else v


def build_q(params: SearchParams) -> str:
    clauses: List[str] = []
    if params.keyword.strip():
        # No field prefix -> ODP searches its default fields. A quoted phrase for
        # "Exact phrase", AND for "All words", OR for "Any word".
        clauses.append(expression(params, "{}"))
    if params.title.strip():
        clauses.append(f"applicationMetaData.inventionTitle:{_phrase(params.title)}")
    if params.author.strip():
        clauses.append(
            f"applicationMetaData.inventorBag.inventorNameText:{_phrase(params.author)}"
        )
    if params.journal.strip():
        clauses.append(
            f"applicationMetaData.applicantBag.applicantNameText:{_phrase(params.journal)}"
        )

    lo = _iso(params.date_start, end=False)
    hi = _iso(params.date_end, end=True)
    if lo or hi:
        span = f"[{lo or '1790-01-01'} TO {hi or '2999-12-31'}]"
        clauses.append(
            f"(applicationMetaData.grantDate:{span} OR "
            f"applicationMetaData.earliestPublicationDate:{span})"
        )

    return " AND ".join(clauses) if clauses else "*:*"


_GRANTED_FILTER = "applicationMetaData.patentNumber:*"
_PENDING_FILTER = (
    "applicationMetaData.earliestPublicationNumber:* "
    "AND NOT applicationMetaData.patentNumber:*"
)


def _query(q: str, limit: int, sort: str, key: str) -> Tuple[List[Article], int]:
    if limit <= 0:
        return [], 0
    try:
        resp = get(
            ENDPOINT,
            params={"q": q, "limit": str(limit), "offset": "0", "sort": sort},
            headers={"X-API-KEY": key},
        )
    except NetworkError as exc:
        # The portal answers "404 No matching records found" when a query finds
        # nothing; that is an empty result, not a failure.
        if "HTTP 404" in str(exc) and "no matching" in str(exc).lower():
            return [], 0
        raise
    try:
        data = resp.json()
    except ValueError as exc:
        raise ValueError(f"Unexpected response from USPTO: {exc}") from exc
    bag = (
        data.get("patentFileWrapperDataBag")
        or data.get("patentBag")
        or data.get("results")
        or []
    )
    if not bag and data.get("error"):
        raise NetworkError(f"USPTO error: {data.get('error')}")
    total = int(data.get("count", len(bag)) or 0)
    return [_parse(w) for w in bag], total


def search(
    params: SearchParams, cfg: Optional[Dict[str, str]] = None
) -> Tuple[List[Article], int]:
    key = _api_key(cfg)
    if not key:
        raise ValueError(
            "USPTO patent search needs a free API key.\n"
            f"Sign in at {KEY_URL}, generate your API key, then paste it into "
            "File -> API Keys & Contact (\"USPTO API key\")."
        )

    base = build_q(params)
    limit = max(1, min(params.max_results, 100))

    # Two passes so results always contain both granted patents and pending
    # (published) applications. Granted first, up to ~60% of the budget; the
    # rest — plus any unused granted slots — goes to pending applications.
    n_granted = max(1, round(limit * 0.6))
    granted, g_total = _query(
        f"{base} AND {_GRANTED_FILTER}",
        n_granted, "applicationMetaData.grantDate desc", key,
    )
    n_pending = limit - len(granted)
    pending, p_total = _query(
        f"{base} AND {_PENDING_FILTER}",
        n_pending, "applicationMetaData.earliestPublicationDate desc", key,
    )

    merged = granted + pending
    merged.sort(key=lambda a: a.date.replace(" (application)", "").strip(), reverse=True)
    return merged, g_total + p_total


def _parse(w: Dict) -> Article:
    meta = w.get("applicationMetaData") or w.get("patentMetaData") or w
    art = Article(source="USPTO Patents", kind="Patent")

    art.title = (
        meta.get("inventionTitle")
        or meta.get("inventionTitleText")
        or meta.get("title")
        or ""
    ).strip()

    inventors: List[str] = []
    for inv in meta.get("inventorBag") or meta.get("inventors") or []:
        name = (
            inv.get("inventorNameText")
            or " ".join(
                p for p in (inv.get("firstName"), inv.get("lastName")) if p
            )
        )
        if name:
            inventors.append(name.strip())
    if not inventors and meta.get("firstInventorName"):
        inventors = [meta["firstInventorName"].strip()]
    art.authors = inventors

    applicants: List[str] = []
    for a in meta.get("applicantBag") or meta.get("applicants") or []:
        name = a.get("applicantNameText") or a.get("name")
        if name:
            applicants.append(name.strip())
    if not applicants and meta.get("firstApplicantName"):
        applicants = [meta["firstApplicantName"].strip()]
    art.journal = "; ".join(applicants)

    grant_date = (meta.get("grantDate") or "").strip()
    pub_date = (meta.get("earliestPublicationDate") or "").strip()
    number = (meta.get("patentNumber") or "").strip().upper()
    pub_number = (meta.get("earliestPublicationNumber") or "").strip().upper()
    app_no = (
        w.get("applicationNumberText")
        or meta.get("applicationNumberText")
        or ""
    ).strip()
    type_code = meta.get("applicationTypeCode", "")

    _ = type_code  # (kept for readability; design detection lives in patlinks)
    if number:
        # Granted patent.
        art.date = grant_date or pub_date
        art.doi = number
        art.link = patent_url(f"US{number}", date_iso=grant_date)
    elif pub_number:
        # Published application — still pending / under examination.
        art.date = f"{pub_date} (application)" if pub_date else "(application)"
        art.doi = pub_number
        art.link = patent_url(pub_number, date_iso=pub_date, is_application=True)
    else:
        art.date = grant_date or pub_date or (meta.get("filingDate") or "").strip()
        art.doi = app_no

    if not art.link and app_no:
        art.link = f"https://patentcenter.uspto.gov/applications/{app_no}"
    return art
