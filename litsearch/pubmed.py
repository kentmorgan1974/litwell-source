# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""PubMed search via NCBI E-utilities (esearch + efetch).

No API key required. An optional key/email (from config) raises the rate
limit and is good API etiquette.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

from .http_client import get
from .models import Article, SearchParams
from .query import expression
from .textutil import clean

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# NCBI recommends batching efetch requests.
_FETCH_BATCH = 100


def _norm_date(value: str) -> str:
    """Turn 'YYYY-MM-DD' / 'YYYY/MM' / 'YYYY' into NCBI's 'YYYY/MM/DD' style."""
    v = value.strip().replace("-", "/")
    return v


def build_term(params: SearchParams) -> str:
    parts: List[str] = []
    kw = expression(params, "{}[Title/Abstract]")
    if kw:
        parts.append(kw)
    if params.title.strip():
        parts.append(f'"{params.title.strip()}"[Title]')
    if params.author.strip():
        parts.append(f'"{params.author.strip()}"[Author]')
    if params.journal.strip():
        parts.append(f'"{params.journal.strip()}"[Journal]')
    return " AND ".join(parts) if parts else "all[sb]"


def _common_params(cfg: Optional[Dict[str, str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if cfg:
        if cfg.get("ncbi_api_key"):
            out["api_key"] = cfg["ncbi_api_key"]
        email = (cfg.get("contact_email") or cfg.get("ncbi_email") or "").strip()
        if email:
            out["email"] = email
            out["tool"] = "litwell"
    return out


def search(
    params: SearchParams, cfg: Optional[Dict[str, str]] = None
) -> Tuple[List[Article], int]:
    """Return (articles, total_found). Raises NetworkError / ValueError on failure."""
    term = build_term(params)
    q: Dict[str, str] = {
        "db": "pubmed",
        "term": term,
        "retmode": "json",
        "retmax": str(max(1, min(params.max_results, 500))),
        # Best matches first when there is a text query, newest first otherwise.
        "sort": "relevance" if (params.keyword.strip() or params.title.strip()) else "pub_date",
    }
    if params.date_start.strip() or params.date_end.strip():
        q["datetype"] = "pdat"
        q["mindate"] = _norm_date(params.date_start) or "1800"
        q["maxdate"] = _norm_date(params.date_end) or "3000"
    q.update(_common_params(cfg))

    resp = get(ESEARCH, params=q)
    try:
        data = resp.json()
        esr = data["esearchresult"]
        pmids: List[str] = esr.get("idlist", [])
        total = int(esr.get("count", "0"))
    except (ValueError, KeyError) as exc:
        raise ValueError(f"Unexpected response from PubMed esearch: {exc}") from exc

    if esr.get("errorlist") or esr.get("warninglist"):
        # Not fatal, but a malformed query often shows up here.
        pass

    articles: List[Article] = []
    for i in range(0, len(pmids), _FETCH_BATCH):
        batch = pmids[i : i + _FETCH_BATCH]
        articles.extend(_efetch(batch, cfg))
    return articles, total


def _efetch(pmids: List[str], cfg: Optional[Dict[str, str]]) -> List[Article]:
    if not pmids:
        return []
    q = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }
    q.update(_common_params(cfg))
    resp = get(EFETCH, params=q)
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        raise ValueError(f"Could not parse PubMed efetch XML: {exc}") from exc

    out: List[Article] = []
    for node in root.findall(".//PubmedArticle"):
        out.append(_parse_article(node))
    # PubmedBookArticle entries occasionally appear; keep them too.
    for node in root.findall(".//PubmedBookArticle"):
        out.append(_parse_article(node))
    return out


def _text(node: Optional[ET.Element]) -> str:
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def _parse_article(node: ET.Element) -> Article:
    art = Article(source="PubMed")

    art.title = _text(node.find(".//ArticleTitle")) or _text(
        node.find(".//BookTitle")
    )

    authors: List[str] = []
    for a in node.findall(".//Author"):
        last = _text(a.find("LastName"))
        fore = _text(a.find("ForeName")) or _text(a.find("Initials"))
        collective = _text(a.find("CollectiveName"))
        if collective:
            authors.append(collective)
        elif last:
            authors.append(f"{last}, {fore}".strip().rstrip(","))
    art.authors = authors

    art.journal = (
        _text(node.find(".//Journal/Title"))
        or _text(node.find(".//Journal/ISOAbbreviation"))
        or _text(node.find(".//MedlineJournalInfo/MedlineTA"))
    )

    art.date = _parse_pubdate(node)

    # Abstract: structured abstracts have several labelled parts.
    parts_txt = []
    for ab in node.findall(".//Abstract/AbstractText"):
        txt = clean(_text(ab))
        label = (ab.get("Label") or "").strip()
        if txt:
            parts_txt.append(f"{label.title()}: {txt}" if label and label.upper() != "UNLABELLED" else txt)
    art.abstract = " ".join(parts_txt)

    art.kind = "Paper"
    for pt in node.findall(".//PublicationType"):
        if _text(pt).lower() == "preprint":
            art.kind = "Preprint"

    pmid = _text(node.find(".//PMID"))
    for aid in node.findall(".//ArticleId"):
        if aid.get("IdType") == "doi":
            art.doi = _text(aid).strip()
            break
    if not art.doi:
        eloc = node.find(".//ELocationID[@EIdType='doi']")
        if eloc is not None:
            art.doi = _text(eloc).strip()
    for aid in node.findall(".//PubmedData/ArticleIdList/ArticleId"):
        if aid.get("IdType") == "pmc" and _text(aid):
            art.oa_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{_text(aid)}/"
            break

    if pmid:
        art.link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    elif art.doi:
        art.link = f"https://doi.org/{art.doi}"
    return art


_MONTHS = {
    m: f"{i:02d}"
    for i, m in enumerate(
        [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
        ],
        start=1,
    )
}


def _parse_pubdate(node: ET.Element) -> str:
    # Prefer the electronic ArticleDate: it is what PubMed's publication-date
    # filter matches on and is usually earlier than the print issue date.
    adate = node.find(".//ArticleDate")
    if adate is not None:
        y = _text(adate.find("Year"))
        m = _text(adate.find("Month"))
        d = _text(adate.find("Day"))
        if y:
            parts = [y]
            if m:
                parts.append(f"{int(m):02d}" if m.isdigit() else m)
            if m and d:
                parts.append(f"{int(d):02d}" if d.isdigit() else d)
            return "-".join(parts)

    pd = node.find(".//JournalIssue/PubDate")
    if pd is None:
        pd = node.find(".//PubDate")
    if pd is None:
        return ""
    year = _text(pd.find("Year"))
    month = _text(pd.find("Month"))
    day = _text(pd.find("Day"))
    if not year:
        medline = _text(pd.find("MedlineDate"))
        return medline
    month = _MONTHS.get(month[:3], month) if month else ""
    parts = [year]
    if month:
        parts.append(month if month.isdigit() else month)
        if day:
            parts.append(f"{int(day):02d}" if day.isdigit() else day)
    return "-".join(parts)
